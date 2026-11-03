import unittest
import zlib
from unittest.mock import patch

from pkxd_server import wire
from pkxd_server.startup import PET_STORE_ID, STORE_IDS, StartupServices


class StartupContractTests(unittest.TestCase):
    def setUp(self):
        self.services = StartupServices()

    def handle(self, name, payload=b""):
        return self.services.handle(name, payload, user_id="local-player", transport_id=7)

    def test_time_matches_native_seconds_and_field_number(self):
        with patch("pkxd_server.startup.time.time", return_value=1700000000.125):
            response = self.handle("time")
        self.assertEqual(response, [("time", bytes.fromhex("1080e2cfaa06"))])
        self.assertIsNone(self.handle("time", wire.number(1, 1)))

    def test_every_versioned_store_gets_its_own_nonnull_tree(self):
        self.assertEqual(len(STORE_IDS), 18)
        for store_id in STORE_IDS:
            with self.subTest(store_id=store_id):
                name, payload = self.handle("store_tree", wire.string(2, store_id))[0]
                response = wire.Proto(payload)
                self.assertEqual((name, response.integer(1)), ("L", 1))
                tree = response.message(3)
                self.assertEqual(tree.text(1), store_id)
                self.assertEqual(tree.text(2), "local-bootstrap-1")
                self.assertEqual(tree.text(3), "pk-xd")
                self.assertNotIn(4, tree.fields)  # Actual empty local product list.

    def test_pet_store_uses_different_response_event_and_tree_field(self):
        name, payload = self.handle("pet_store_tree", wire.string(2, PET_STORE_ID))[0]
        response = wire.Proto(payload)
        self.assertEqual((name, response.integer(1), response.integer(3)), ("PST", 1, 0))
        self.assertEqual(response.message(4).text(1), PET_STORE_ID)
        self.assertNotIn(3, response.fields)

    def test_unknown_store_and_check_ids_return_explicit_failures(self):
        for name in ("store_tree", "pet_store_tree"):
            _, payload = self.handle(name, wire.string(2, "unknown-store"))[0]
            response = wire.Proto(payload)
            self.assertEqual(response.integer(1), 0)
            self.assertTrue(response.text(2))
            self.assertEqual(response.message(4 if name == "pet_store_tree" else 3).text(1), "unknown-store")
        valid = wire.number(1, 1) + b"".join(wire.string(2, store_id) for store_id in STORE_IDS)
        self.assertEqual(self.handle("store_tree", valid), [("L2", b"\x08\x01")])
        name, payload = self.handle("store_tree", valid + wire.string(2, "unknown"))[0]
        self.assertEqual((name, wire.Proto(payload).integer(1)), ("L2", 0))

    def test_empty_npc_response_is_present_and_friends_use_their_own_schema(self):
        self.assertEqual(self.handle("npc/fetch-owned"), [("npc/fetch-owned", b"")])
        self.assertEqual(self.handle("friends"), [("get_friends_result", b"\x08\x01")])
        self.assertIsNone(self.handle("friends", b"\x08\x01"))  # Invite is not implemented.

    def test_game_cache_accepts_csharp_negative_world_owner(self):
        request = bytes.fromhex("080310ffffffffffffffffff01")
        self.assertEqual(len(request), 13)
        self.assertEqual(wire.Proto(request).int32(2), -1)
        self.assertEqual(self.handle("game_variable", request), [("q", b"")])
        with self.assertRaises(wire.ProtocolError):
            self.handle("game_variable", wire.number(1, 3) + wire.number(2, 8))
        self.assertIsNone(self.handle("game_variable", b""))  # World mutation is not acknowledged.

    def test_pet_list_cache_and_remote_lookup_have_distinct_response_ids(self):
        self.assertEqual(self.handle("pet"), [("pet", bytes.fromhex("08081001"))])
        self.assertEqual(self.handle("pet", bytes.fromhex("0806")), [("pet", bytes.fromhex("0807"))])
        payload = wire.number(1, 28) + wire.string(2, "local-player")
        self.assertEqual(self.handle("pet", payload), [("pet", bytes.fromhex("0824"))])
        self.assertIsNone(self.handle("pet", b"\x08\x01"))  # Purchase stays unsupported.
        self.assertIsNone(self.handle("pet", wire.number(1, 28) + wire.string(2, "someone-else")))

    def test_observed_pet_operation_16_reads_owner_and_returns_needs_event_21(self):
        user_id = "12345678-1234-1234-1234-123456789012"
        request = wire.number(1, 16) + wire.string(2, user_id)
        self.assertEqual(len(request), 40)
        self.assertEqual(self.services.handle("pet", request, user_id=user_id, transport_id=7),
                         [("pet", bytes.fromhex("0815"))])
        self.assertIsNone(self.handle("pet", request))

    def test_new_post_inventory_query_schemas_and_response_ids(self):
        self.assertEqual(self.handle("hair_style"), [("get_hair_styles", bytes.fromhex("0801"))])
        self.assertEqual(self.handle("lb"), [("lb", bytes.fromhex("1801"))])
        self.assertEqual(self.handle("pet", bytes.fromhex("0813")), [("pet", bytes.fromhex("0818"))])
        self.assertEqual(self.handle("pet", bytes.fromhex("0818")), [("pet", bytes.fromhex("0820"))])
        self.assertIsNone(self.handle("lb", bytes.fromhex("0802")))  # Purchase is not supported.

    def test_world_vehicle_queries_and_pet_evolution_use_native_response_schemas(self):
        self.assertEqual(self.handle("vhc"), [("vhc", bytes.fromhex("1001"))])
        self.assertEqual(self.handle("vhc", b"\x08\x05"), [("vhc", b"\x08\x05")])
        self.assertEqual(self.handle("pet", b"\x08\x0d"), [("pet", b"\x08\x13")])
        for purchase_or_spawn in (1, 6, 7):
            self.assertIsNone(self.handle("vhc", wire.number(1, purchase_or_spawn)))

    def test_day_state_and_empty_position_snapshot_use_different_codecs(self):
        self.assertEqual(self.handle("init_day_night"), [("G", bytes.fromhex("1001"))])
        name, compressed = self.handle("init_pos")[0]
        self.assertEqual((name, compressed), ("C", bytes.fromhex("0300")))
        self.assertEqual(zlib.decompress(compressed, wbits=-15), b"")
        self.assertEqual(self.handle("fetch_events"), [])

    def test_analytics_are_one_way_and_ids_are_not_logged(self):
        sentinel = b"private-device-id-do-not-log"
        with self.assertLogs("pkxd_server.startup", level="INFO") as logs:
            for name in ("Analytics/sessionId", "Analytics/deviceId"):
                self.assertEqual(self.handle(name, sentinel), [])
            self.handle("time")
        self.assertNotIn(sentinel.decode(), " ".join(logs.output))

    def test_malformed_requests_and_unhandled_domains_do_not_receive_success(self):
        for name, payload in (("time", b"\x08"), ("store_tree", b"\x12\x20x"),
                              ("store_tree", b""), ("npc/fetch-owned", b"\x08\x01"),
                              ("store_tree", wire.number(1, 1) + wire.number(2, 1))):
            with self.subTest(name=name), self.assertRaises(wire.ProtocolError):
                self.handle(name, payload)
        for name in ("fruit", "matchmaking", "hwn", "slot_interaction", "unknown"):
            self.assertIsNone(self.handle(name))


if __name__ == "__main__":
    unittest.main()
