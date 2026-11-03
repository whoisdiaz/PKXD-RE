import hashlib
import http.client
import json
import socket
import struct
import tempfile
import threading
import time
import unittest
from pathlib import Path

from pkxd_server.accounts import AccountError, AccountStore, AUTH, REISSUE, SIGN_UP, USER
from pkxd_server.game import GameServer
from pkxd_server.lobby import GameDestination, LobbyServer
from pkxd_server.version_policy import VersionPolicy
from pkxd_server import wire


class WireEvidenceTests(unittest.TestCase):
    def test_golden_native_messages(self):
        # Literal independent examples: BE framing, byte ASCII name length,
        # protobuf LoginRequest fields 1/3 and LoginResponse fields 1/3/4.
        self.assertEqual(wire.frame(b"\x03"), bytes.fromhex("0000000103"))
        self.assertEqual(wire.event("login", bytes.fromhex("080118012001")),
                         bytes.fromhex("05056c6f67696e080118012001"))
        request = wire.Proto(bytes.fromhex("0a036162631a06312e33382e34"))
        self.assertEqual((request.text(1), request.text(3)), ("abc", "1.38.4"))
        self.assertEqual(wire.variable(7, "j", b"\x05\x10\x20\x30"),
                         bytes.fromhex("00000007000000016a05102030"))
        self.assertEqual(wire.client_variable_update("j", b"\x05\x10\x20\x30"),
                         bytes.fromhex("000000016a05102030"))
        self.assertEqual(wire.number(3, 1700000000000), bytes.fromhex("1880d095ffbc31"))

    def test_malformed_protobuf_is_rejected(self):
        for data in (b"\x00", b"\x0a\x20x", b"\x08\x80", b"\x08" + b"\xff" * 10,
                     b"\x0b", b"\x09\x00"):
            with self.subTest(data=data), self.assertRaises(wire.ProtocolError):
                wire.Proto(data)
        with self.assertRaises(wire.ProtocolError):
            wire.Proto(b"\x08\x01").text(1)
        with self.assertRaises(wire.ProtocolError):
            wire.Proto(b"\x0a\x01\xff").text(1)

    def test_packed_and_unpacked_integer_fields(self):
        self.assertEqual(wire.Proto(bytes.fromhex("08010a0202030804")).integers(1), [1, 2, 3, 4])
        with self.assertRaises(wire.ProtocolError):
            wire.Proto(bytes.fromhex("0a0180")).integers(1)

    def test_client_variable_payload_has_no_owner_prefix(self):
        data = bytes.fromhex("000000016a05102030")
        self.assertEqual(wire.parse_client_variable_update(data), ("j", b"\x05\x10\x20\x30"))
        for malformed in (b"", bytes.fromhex("00000000"), bytes.fromhex("000000046a05"),
                          bytes.fromhex("000000016a"),
                          wire.variable(1, "j", b"\x05\x10\x20\x30")):
            with self.subTest(data=malformed), self.assertRaises(wire.ProtocolError):
                wire.parse_client_variable_update(malformed)
        # Type validity is checked by the update policy after structural parsing.
        self.assertEqual(wire.parse_client_variable_update(bytes.fromhex("000000016aff")), ("j", b"\xff"))


class CharacterFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.temp.name) / "players.sqlite3"
        cls.store = AccountStore(cls.db_path)
        cls.game = GameServer(("127.0.0.1", 0), cls.store, VersionPolicy())
        cls.http = LobbyServer(("127.0.0.1", 0),
                               GameDestination("127.0.0.1", cls.game.server_address[1]),
                               store=cls.store, game=cls.game)
        cls.threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in (cls.game, cls.http)]
        for thread in cls.threads:
            thread.start()

    @classmethod
    def tearDownClass(cls):
        for server in (cls.http, cls.game):
            server.shutdown()
            server.server_close()
        for thread in cls.threads:
            thread.join(timeout=5)
        cls.temp.cleanup()

    def request(self, path, payload=None, method="POST", headers=None):
        connection = http.client.HTTPConnection(*self.http.server_address, timeout=3)
        try:
            connection.request(method, path, body=None if method == "GET" else json.dumps(payload),
                               headers={"Content-Type": "application/json", **(headers or {})})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def account(self):
        status, identity = self.request(SIGN_UP, {"deviceInfo": {}})
        self.assertEqual(status, 200)
        status, auth = self.request(AUTH, {"identityProvider": "FASTER", "credentials":
                                          {"type": "TOKEN", "token": identity["token"]}})
        self.assertEqual(status, 200)
        status, user = self.request(USER, {"authToken": auth["authToken"]})
        self.assertEqual(status, 200)
        self.assertEqual(user["userId"], auth["userId"])
        self.assertEqual(user["authSessionId"], auth["sessionId"])
        return identity, auth, user

    def tcp(self, token, *, reconnect=False, version="1.38.4", fragmented=False):
        sock = socket.create_connection(self.game.server_address, timeout=3)
        self.addCleanup(sock.close)
        packet = wire.frame(b"\x04cached-key" if reconnect else b"\x03")
        if fragmented:
            for value in packet:
                sock.sendall(bytes((value,)))
        else:
            sock.sendall(packet)
        connected = wire.receive(sock)
        self.assertEqual(connected[0], 3)
        transport_id = wire.I32.unpack(connected[1:5])[0]
        self.assertEqual(len(connected[5:]), 32)
        sock.sendall(wire.frame(wire.event("login", wire.string(1, token) + wire.string(3, version))))
        name, payload = wire.parse_event(wire.receive(sock))
        self.assertEqual(name, "login")
        return sock, transport_id, wire.Proto(payload)

    def bootstrap(self, sock, transport_id):
        joined = wire.receive(sock)
        self.assertEqual(joined, b"\x06\x01" + struct.pack(">ii", 1, transport_id))
        values = {}
        for _ in range(14):
            packet = wire.receive(sock)
            name, payload = wire.parse_event(packet)
            self.assertIn(name, ("tbulv", "tbugv"))
            owner, key, typed_value = wire.parse_variable(payload)
            self.assertEqual(owner, transport_id)
            values[(name, key)] = typed_value
        for key in ("p", "o", "wa", "j", "s", "i", "hs"):
            self.assertIn(("tbulv", key), values)
        self.assertEqual(values[("tbulv", "i")], b"\x03\x00")
        self.assertEqual(values[("tbulv", "s")], b"\x05")
        self.assertEqual(values[("tbulv", "A")], b"\x02\x00\x00\x00\x00")
        self.assertEqual(values[("tbulv", "I")], b"\x04\x00")
        return values

    def test_full_http_tcp_character_and_persistence(self):
        identity, auth, user = self.account()
        status, allocation = self.request("/lobby/allocation", {
            "userToken": user["userToken"], "gameServerProtocolVersion": "0.2.49", "isPrivate": False})
        self.assertEqual((status, allocation["successful"]), (200, True))
        sock, player_id, response = self.tcp(user["userToken"], fragmented=True)
        self.assertEqual((response.integer(1), response.integer(3), response.integer(4)), (1, 1, 1))
        values = self.bootstrap(sock, player_id)
        self.assertEqual(values[("tbulv", "k")], b"\x01" + user["userId"].encode())
        # Cosmetic and nickname are persisted through actual TCP requests.
        skin = b"\x05\x30\x60\x90"
        sock.sendall(wire.frame(wire.event("tbulv", wire.client_variable_update("j", skin), room=True)))
        name, payload = wire.parse_event(wire.receive(sock))
        self.assertEqual((name, wire.parse_variable(payload)), ("tbulv", (player_id, "j", skin)))
        sock.sendall(wire.frame(wire.event("profile_update", wire.string(2, "CodexTeste"), room=True)))
        name, payload = wire.parse_event(wire.receive(sock))
        self.assertEqual((name, wire.Proto(payload).text(1)), ("set_name_result", "CodexTeste"))
        for _ in range(2):
            wire.receive(sock)  # Nickname variables.
        sock.close()
        reopened_store = AccountStore(self.db_path)
        persisted = reopened_store.user(user["userToken"])
        self.assertEqual(persisted["nickname"], "CodexTeste")
        self.assertEqual(persisted["character_created"], 1)
        self.assertEqual(json.loads(persisted["cosmetics"])["j"], skin.hex())
        # Same identity obtains fresh sessions for the same persistent player.
        status, auth2 = self.request(AUTH, {"identityProvider": "FASTER", "credentials":
                                          {"type": "TOKEN", "token": identity["token"]}})
        self.assertEqual(status, 200)
        status, user2 = self.request(USER, {"authToken": auth2["authToken"]})
        self.assertEqual(user2["userId"], user["userId"])
        sock2, player_id2, response2 = self.tcp(user2["userToken"], reconnect=True)
        self.assertEqual((response2.integer(1), response2.integer(3)), (1, 0))
        # Transport IDs belong to the room and may be reused after disconnect;
        # the authenticated persistent UUID remains the account identity.
        self.assertTrue(1 <= player_id2 <= 255)
        values2 = self.bootstrap(sock2, player_id2)
        self.assertEqual(values2[("tbulv", "j")], skin)
        self.assertEqual(values2[("tbulv", "m")], b"\x01CodexTeste")

    def test_session_refresh_and_no_tokens_in_logs_or_database(self):
        with self.assertLogs("pkxd_server.lobby", level="INFO") as logs:
            identity, auth, user = self.account()
            status, response = self.request(AUTH + "/" + auth["authToken"], method="GET")
        self.assertEqual((status, response["userId"]), (200, user["userId"]))
        status, refreshed = self.request(REISSUE, {"authToken": auth["authToken"]})
        self.assertEqual(status, 200)
        self.assertNotEqual(refreshed["authToken"], auth["authToken"])
        status, user2 = self.request(USER, {"authToken": refreshed["authToken"]})
        self.assertEqual(user2["userId"], user["userId"])
        for token in (identity["token"], auth["authToken"], user["userToken"]):
            self.assertNotIn(token, " ".join(logs.output))
            self.assertNotIn(token.encode(), self.db_path.read_bytes())

    def test_invalid_tokens_types_and_expiry_do_not_create_sessions(self):
        _, auth, user = self.account()
        for token in ("unknown", user["userToken"], None, [], "\ud800"):
            status, _ = self.request(USER, {"authToken": token})
            self.assertEqual(status, 401)
        status, _ = self.request(AUTH, {"identityProvider": "GOOGLE", "credentials": {"type": "TOKEN", "token": "x"}})
        self.assertEqual(status, 400)
        with self.store.connect() as db:
            db.execute("UPDATE tokens SET expires_at=? WHERE digest=?",
                       (int(time.time()) - 1, hashlib.sha256(auth["authToken"].encode()).hexdigest()))
        self.assertEqual(self.request(USER, {"authToken": auth["authToken"]})[0], 401)
        self.assertEqual(self.request("/lobby/allocation", {"userToken": "unknown",
                         "gameServerProtocolVersion": "0.2.49", "isPrivate": False})[0], 401)

    def test_identity_lookup_requires_the_correct_user_bearer_token(self):
        _, auth, user = self.account()
        path = "/v1/users/identities"
        for token in ("unknown", auth["authToken"]):
            status, response = self.request(path, method="GET", headers={"Authorization": "Bearer " + token})
            self.assertEqual((status, response["statusCode"], response["status"]), (401, 401, "UNAUTHORIZED"))
        status, response = self.request(path, method="GET", headers={"Authorization": "Bearer " + user["userToken"]})
        self.assertEqual(status, 200)
        self.assertEqual(response["response"][0]["key"], user["userId"])
        self.assertEqual(response["response"][0]["type"], "anonymous")

    def test_game_login_checks_token_and_app_version(self):
        _, _, user = self.account()
        for token, version in (("unknown", "1.38.4"), (user["userToken"], "1.38.5")):
            sock, _, response = self.tcp(token, version=version)
            self.assertEqual(response.integer(1), 0)
            self.assertTrue(response.text(2))
            self.assertEqual(sock.recv(1), b"")

    def test_startup_sequence_after_game_login_receives_actual_room_replies(self):
        from pkxd_server.startup import STORE_IDS, PET_STORE_ID
        _, _, user = self.account()
        sock, player_id, _ = self.tcp(user["userToken"])
        self.bootstrap(sock, player_id)
        requests = [("Analytics/sessionId", b"session-id"), ("Analytics/deviceId", b"device-id"),
                    ("friends", b""), ("pet", wire.number(1, 28) + wire.string(2, user["userId"])),
                    ("npc/fetch-owned", b""), ("game_variable", bytes.fromhex("080310ffffffffffffffffff01")),
                    ("time", b"")]
        requests += [("store_tree", wire.string(2, store_id)) for store_id in STORE_IDS]
        requests += [("pet_store_tree", wire.string(2, PET_STORE_ID)),
                     ("profile_update", wire.number(1, 5))]
        sock.sendall(b"".join(wire.frame(wire.event(name, payload, room=True)) for name, payload in requests))
        names = []
        trees = []
        for _ in range(len(requests) - 2):  # Analytics expects no acknowledgement.
            packet = wire.receive(sock)
            self.assertEqual(packet[0], wire.ROOM_EVENT)
            name, payload = wire.parse_event(packet)
            response = wire.Proto(payload)
            names.append(name)
            if name == "L":
                self.assertEqual(response.integer(1), 1)
                trees.append(response.message(3).text(1))
            elif name == "time":
                self.assertLess(abs(response.integer(2) - time.time()), 5)
            elif name == "Q":
                self.assertEqual((response.text(3), response.text(4), response.integer(6)), ("GET", "", 0))
        self.assertEqual(names, ["get_friends_result", "pet", "npc/fetch-owned", "q", "time"]
                         + ["L"] * len(STORE_IDS) + ["PST", "Q"])
        self.assertEqual(trees, list(STORE_IDS))
        sock.sendall(wire.frame(b"\x01"))
        self.assertEqual(wire.receive(sock), b"\x02")
        self.assertEqual(self.store.user(user["userToken"])["terms"], "")

    def test_startup_data_cannot_be_requested_before_game_login(self):
        for name, payload in (("time", b""), ("fruit", b"\x08\x03"),
                              ("matchmaking", b"\x08\x02\x10\x03"),
                              ("hwn", b"\x08\x03"), ("referral", b"")):
            with self.subTest(name=name), socket.create_connection(self.game.server_address, timeout=3) as sock:
                sock.sendall(wire.frame(b"\x03"))
                wire.receive(sock)
                sock.sendall(wire.frame(wire.event(name, payload, room=True)))
                self.assertEqual(sock.recv(1), b"")

    def test_remaining_startup_queries_reply_in_room_before_movement_without_changing_account(self):
        _, _, user = self.account()
        sock, transport_id, _ = self.tcp(user["userToken"])
        self.bootstrap(sock, transport_id)
        before = self.store.user(user["userToken"])
        inventory = self.store.inventory(before["id"])
        # Exact native request bodies; four previously unanswered domains,
        # interspersed with one-way analytics and client position updates.
        requests = [("fruit", bytes.fromhex("0803")),
                    ("Analytics/sessionId", b"local-diagnostic"),
                    ("matchmaking", bytes.fromhex("08021003")),
                    ("hwn", bytes.fromhex("0803")), ("referral", b""),
                    ("C", bytes.fromhex("01ff3f800000400000004040000042b40000"))]
        sock.sendall(b"".join(wire.frame(wire.event(name, payload, room=True)) for name, payload in requests)
                     + wire.frame(b"\x01"))
        expected = [("fruit-quest-count", b""), ("matchmaking_lobby_state", b"\x18\x03"),
                    ("hwn", b"\x08\x03"), ("N", bytes.fromhex("120408011a00"))]
        for response in expected:
            packet = wire.receive(sock)
            self.assertEqual(packet[0], wire.ROOM_EVENT)
            self.assertEqual(wire.parse_event(packet), response)
        self.assertEqual(wire.receive(sock), b"\x02")
        with self.game.lock:
            self.assertEqual(self.game.world_sessions[transport_id].movement_packets, 1)
        self.assertEqual(self.store.user(user["userToken"]), before)
        self.assertEqual(self.store.inventory(before["id"]), inventory)

    def test_inventory_bootstrap_contains_default_id_quantity_pairs_and_18_slots(self):
        _, _, user = self.account()
        sock, player_id, _ = self.tcp(user["userToken"])
        values = self.bootstrap(sock, player_id)
        inventory = values[("tbulv", "p")]
        self.assertEqual(inventory[0], 6)
        pairs = list(struct.iter_unpack(">ii", inventory[1:]))
        self.assertEqual(pairs, [(5, 1), (13, 1), (15, 1), (16, 1), (17, 1), (59, 1), (272, 1), (273, 1), (4636, 1)])
        equipped = values[("tbulv", "o")]
        slots = [item[0] for item in struct.iter_unpack(">i", equipped[1:])]
        self.assertEqual(slots, [0, 0, 0, 0, 4636, 16, 5, 13, 272, 15, 273, 17, 17, 59, 59, 0, 0, 0])

    def test_native_variable_updates_do_not_disconnect_and_replies_add_authenticated_owner(self):
        _, _, user = self.account()
        sock, player_id, _ = self.tcp(user["userToken"])
        self.bootstrap(sock, player_id)
        # Role remains server-owned; a denied write must not break framing.
        sock.sendall(wire.frame(wire.event("tbulv", bytes.fromhex("00000001440200000001"), room=True))
                     + wire.frame(wire.event("tbulv", bytes.fromhex("000000016a05102030"), room=True)))
        name, payload = wire.parse_event(wire.receive(sock))
        self.assertEqual(name, "tbulv")
        self.assertEqual(wire.parse_variable(payload), (player_id, "j", b"\x05\x10\x20\x30"))
        sock.sendall(wire.frame(b"\x01"))
        self.assertEqual(wire.receive(sock), b"\x02")
        self.assertEqual(json.loads(self.store.user(user["userToken"])["cosmetics"]), {"j": "05102030"})

    def test_rejection_log_identifies_validation_without_logging_session_payload(self):
        _, _, user = self.account()
        sock, player_id, _ = self.tcp(user["userToken"])
        self.bootstrap(sock, player_id)
        with self.assertLogs("pkxd_server.game", level="INFO") as logs:
            sock.sendall(wire.frame(wire.event("tbulv", wire.variable(1, "j", b"\x05\x10\x20\x30"), room=True)))
            self.assertEqual(sock.recv(1), b"")
        output = " ".join(logs.output)
        self.assertIn('opcode=8 event="tbulv" reason=Invalid client variable key', output)
        self.assertNotIn(user["userToken"], output)

    def test_post_inventory_replay_keeps_connection_after_native_variable_write(self):
        _, _, user = self.account()
        sock, player_id, _ = self.tcp(user["userToken"])
        self.bootstrap(sock, player_id)
        requests = [("hair_style", b""), ("lb", b""), ("fetch_events", b""),
                    ("init_pos", b""), ("init_day_night", b""), ("pet", b"\x08\x13"),
                    ("pet", b"\x08\x18"), ("pet", b"\x08\x06"),
                    ("slot_interaction", b"\x08\x03" + wire.string(3, user["userId"])),
                    ("tbulv", bytes.fromhex("000000016a05102030"))]
        sock.sendall(b"".join(wire.frame(wire.event(name, payload, room=True)) for name, payload in requests))
        responses = [wire.parse_event(wire.receive(sock)) for _ in range(8)]
        self.assertEqual(responses[:7], [("get_hair_styles", b"\x08\x01"), ("lb", b"\x18\x01"),
                                        ("C", b"\x03\x00"), ("G", b"\x10\x01"),
                                        ("pet", b"\x08\x18"), ("pet", b"\x08\x20"), ("pet", b"\x08\x07")])
        self.assertEqual(responses[7][0], "tbulv")
        self.assertEqual(wire.parse_variable(responses[7][1]), (player_id, "j", b"\x05\x10\x20\x30"))
        sock.sendall(wire.frame(b"\x01"))
        self.assertEqual(wire.receive(sock), b"\x02")

    def test_world_startup_replay_position_and_layer_survive_keepalive(self):
        _, _, user = self.account()
        sock, transport_id, _ = self.tcp(user["userToken"])
        self.bootstrap(sock, transport_id)
        requests = [("slot_interaction", b"\x08\x02" + wire.string(3, user["userId"])),
                    ("pet", b"\x08\x0d"), ("vhc", b""), ("vhc", b"\x08\x05"),
                    ("C", bytes.fromhex("01ff3f800000400000004040000042b40000")),
                    ("PL", bytes.fromhex("00000000003f800000400000004040000042b40000"))]
        sock.sendall(b"".join(wire.frame(wire.event(name, body, room=True)) for name, body in requests)
                     + wire.frame(b"\x01"))
        replies = [wire.parse_event(wire.receive(sock)) for _ in range(4)]
        self.assertEqual(replies, [("n", b""), ("pet", b"\x08\x13"), ("vhc", b"\x10\x01"), ("vhc", b"\x08\x05")])
        self.assertEqual(wire.receive(sock), b"\x02")
        with self.game.lock:
            state = self.game.world_sessions[transport_id]
        self.assertEqual((state.layer, state.sequence, state.position, state.movement_packets),
                         (0, 0, (1., 2., 3., 90.), 2))
        # Leaving removes transient room state while the account remains valid.
        sock.sendall(wire.frame(bytes((wire.LEAVE,)) + wire.I32.pack(1)))
        self.assertEqual(wire.receive(sock), b"\x07" + wire.I32.pack(1))
        with self.game.lock:
            self.assertNotIn(transport_id, self.game.world_sessions)
        sock.sendall(wire.frame(bytes((wire.JOIN,)) + wire.I32.pack(1)))
        self.bootstrap(sock, transport_id)
        with self.game.lock:
            self.assertIsNone(self.game.world_sessions[transport_id].position)
        self.assertEqual(json.loads(self.store.user(user["userToken"])["cosmetics"]), {})

    def test_runtime_flags_are_acknowledged_but_not_saved_as_cosmetics(self):
        _, _, user = self.account()
        sock, transport_id, _ = self.tcp(user["userToken"])
        self.bootstrap(sock, transport_id)
        value = b"\x04\x01"
        sock.sendall(wire.frame(wire.event("tbulv", wire.client_variable_update("h", value), room=True)))
        name, payload = wire.parse_event(wire.receive(sock))
        self.assertEqual((name, wire.parse_variable(payload)), ("tbulv", (transport_id, "h", value)))
        self.assertEqual(json.loads(self.store.user(user["userToken"])["cosmetics"]), {})
        other, other_id, _ = self.tcp(user["userToken"])
        self.assertNotEqual(other_id, transport_id)  # Both connections are live.
        self.bootstrap(other, other_id)
        with self.game.lock:
            self.assertNotIn("h", self.game.world_sessions[other_id].variables)

    def test_avatar_animation_is_echoed_for_authenticated_owner_without_persisting(self):
        _, _, user = self.account()
        sock, transport_id, _ = self.tcp(user["userToken"])
        self.bootstrap(sock, transport_id)
        # Present empty objects are safe for all five native animation readers.
        animation = bytes.fromhex("050a0012001a0022002a00")
        update = wire.event("tbulv", wire.client_variable_update("aaa", animation), room=True)
        sock.sendall(wire.frame(update))
        name, payload = wire.parse_event(wire.receive(sock))
        self.assertEqual((name, wire.parse_variable(payload)), ("tbulv", (transport_id, "aaa", animation)))
        with self.game.lock:
            self.assertEqual(self.game.world_sessions[transport_id].animation_updates, 1)
        self.assertEqual(json.loads(self.store.user(user["userToken"])["cosmetics"]), {})
        # A missing nested object is rejected without closing the session.
        bad = wire.event("tbulv", wire.client_variable_update("aaa", animation[:-2]), room=True)
        sock.sendall(wire.frame(bad) + wire.frame(b"\x01"))
        self.assertEqual(wire.receive(sock), b"\x02")
        sock.sendall(wire.frame(bytes((wire.LEAVE,)) + wire.I32.pack(1)))
        wire.receive(sock)
        sock.sendall(wire.frame(bytes((wire.JOIN,)) + wire.I32.pack(1)))
        self.bootstrap(sock, transport_id)
        with self.game.lock:
            self.assertNotIn("aaa", self.game.world_sessions[transport_id].variables)

    def test_world_events_require_authentication_and_room_membership(self):
        for name, body in (("C", bytes(18)), ("PL", bytes(21)), ("slot_interaction", b"\x08\x02")):
            with socket.create_connection(self.game.server_address, timeout=3) as sock:
                sock.sendall(wire.frame(b"\x03"))
                wire.receive(sock)
                sock.sendall(wire.frame(wire.event(name, body, room=True)))
                self.assertEqual(sock.recv(1), b"")
        _, _, user = self.account()
        sock, transport_id, _ = self.tcp(user["userToken"])
        self.bootstrap(sock, transport_id)
        sock.sendall(wire.frame(bytes((wire.LEAVE,)) + wire.I32.pack(1)))
        wire.receive(sock)
        sock.sendall(wire.frame(wire.event("C", bytes(18), room=True)))
        self.assertEqual(sock.recv(1), b"")

    def test_room_transport_ids_are_recycled_without_overflowing_native_byte(self):
        for _ in range(260):
            with socket.create_connection(self.game.server_address, timeout=3) as sock:
                sock.sendall(wire.frame(b"\x03"))
                connected = wire.receive(sock)
                transport_id = wire.I32.unpack(connected[1:5])[0]
                self.assertTrue(1 <= transport_id <= 255)

    def test_backpack_initial_query_and_updates_use_success_oneof_and_preserve_ownership(self):
        _, _, user = self.account()
        sock, player_id, _ = self.tcp(user["userToken"])
        self.bootstrap(sock, player_id)
        sock.sendall(wire.frame(wire.event("backpack", b"\x08\x02", room=True)))
        self.assertEqual(wire.receive(sock), bytes.fromhex("08086261636b7061636b08021200"))
        sock.sendall(wire.frame(wire.event("backpack", bytes.fromhex("080212020510"), room=True)))
        name, payload = wire.parse_event(wire.receive(sock))
        self.assertEqual(name, "backpack")
        self.assertEqual(wire.Proto(payload).message(2).integers(1), [5, 16])
        sock.sendall(wire.frame(wire.event("backpack", wire.number(1, 2) + wire.number(2, 123456), room=True)))
        _, payload = wire.parse_event(wire.receive(sock))
        response = wire.Proto(payload)
        self.assertIn(3, response.fields)
        self.assertNotIn(2, response.fields)
        self.assertTrue(response.message(3).text(1))
        sock.sendall(wire.frame(wire.event("backpack", b"\x08\x02", room=True)))
        _, payload = wire.parse_event(wire.receive(sock))
        self.assertEqual(wire.Proto(payload).message(2).integers(1), [5, 16])
        player = self.store.user(user["userToken"])
        self.assertNotIn(123456, self.store.inventory(player["id"]))
        self.assertEqual(AccountStore(self.db_path).update_favorites(player["id"], [], []), [5, 16])

    def test_prelogin_profile_and_bad_frames_are_closed(self):
        for bad in (struct.pack(">i", -1), struct.pack(">i", wire.MAX_FRAME + 1),
                    wire.frame(wire.event("profile_update", wire.string(2, "NoAuth"), room=True))):
            with socket.create_connection(self.game.server_address, timeout=3) as sock:
                sock.sendall(wire.frame(b"\x03"))
                wire.receive(sock)
                sock.sendall(bad)
                self.assertEqual(sock.recv(1), b"")

    def test_variable_ownership_and_wallet_writes(self):
        _, _, user = self.account()
        sock, player_id, _ = self.tcp(user["userToken"])
        self.bootstrap(sock, player_id)
        sock.sendall(wire.frame(wire.event("tbulv", wire.client_variable_update("wa", b"\x05\x08\x64"), room=True))
                     + wire.frame(b"\x01"))
        self.assertEqual(wire.receive(sock), b"\x02")
        player = self.store.user(user["userToken"])
        self.assertEqual(json.loads(player["cosmetics"]), {})
        sock.sendall(wire.frame(wire.event("tbulv", wire.variable(player_id + 1, "j", b"\x05\x01\x02\x03"), room=True)))
        self.assertEqual(sock.recv(1), b"")

    def test_native_equip_message_saves_outfit_skin_and_hair_together(self):
        _, _, user = self.account()
        sock, player_id, _ = self.tcp(user["userToken"])
        self.bootstrap(sock, player_id)
        # Packed Items [1,2,3,4], Color {R:16,G:32,B:48}, HairStyle:7.
        payload = bytes.fromhex("0a040102030412060810102018302007")
        sock.sendall(wire.frame(wire.event("equip", payload, room=True)))
        values = {}
        for _ in range(3):
            name, data = wire.parse_event(wire.receive(sock))
            self.assertEqual(name, "tbulv")
            owner, key, value = wire.parse_variable(data)
            self.assertEqual(owner, player_id)
            values[key] = value
        self.assertEqual(values, {"o": b"\x06" + struct.pack(">iiii", 1, 2, 3, 4),
                                  "j": b"\x05\x10\x20\x30", "hs": b"\x02" + wire.I32.pack(7)})
        stored = json.loads(self.store.user(user["userToken"])["cosmetics"])
        self.assertEqual(stored, {key: value.hex() for key, value in values.items()})
        malformed = bytes.fromhex("0a04010203041203088002")  # R=256 is outside a byte.
        sock.sendall(wire.frame(wire.event("equip", malformed, room=True)))
        self.assertEqual(sock.recv(1), b"")
        self.assertEqual(json.loads(self.store.user(user["userToken"])["cosmetics"]), stored)

    def test_terms_and_consent_only_change_after_explicit_request(self):
        _, _, user = self.account()
        sock, player_id, _ = self.tcp(user["userToken"])
        self.bootstrap(sock, player_id)
        sock.sendall(wire.frame(wire.event("profile_update", wire.number(1, 5), room=True)))
        name, payload = wire.parse_event(wire.receive(sock))
        response = wire.Proto(payload)
        self.assertEqual((name, response.text(3), response.text(4), response.integer(6)), ("Q", "GET", "", 0))
        sock.sendall(wire.frame(wire.event("profile_update", wire.number(1, 4) + wire.string(2, "local-test"), room=True)))
        name, payload = wire.parse_event(wire.receive(sock))
        self.assertEqual((name, wire.Proto(payload).text(3)), ("Q", "SET"))
        self.assertEqual(self.store.user(user["userToken"])["terms"], "local-test")
        self.assertEqual(self.store.user(user["userToken"])["ads_consent"], 0)

    def test_name_validation_collision_and_existing_character(self):
        _, _, a = self.account()
        _, _, b = self.account()
        player_a, player_b = self.store.user(a["userToken"]), self.store.user(b["userToken"])
        for name in ("", "x", "x" * 25, "ab\x00cd"):
            with self.assertRaises(AccountError):
                self.store.set_name(player_a["id"], name)
        self.assertEqual(self.store.set_name(player_a["id"], " José "), "José")
        self.assertEqual(self.store.set_name(player_a["id"], "José"), "José")
        with self.assertRaises(AccountError):
            self.store.set_name(player_b["id"], "JOSÉ")
        with self.assertRaises(AccountError):
            self.store.set_name(player_a["id"], "OutroNome")


if __name__ == "__main__":
    unittest.main()
