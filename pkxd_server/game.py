"""Local accounts, characters and single-player world sessions for ToxicBird."""
import json
import logging
import secrets
import socket
import socketserver
import struct
import threading
import time

from .accounts import AccountError
from .avatar_defaults import DEFAULT_EQUIPPED_ITEMS
from .inventory import InventoryServices
from .startup import REQUESTS, StartupServices
from .world import INITIAL_VARIABLES, REQUESTS as WORLD_REQUESTS, LocalWorldSession
from . import wire

LOG = logging.getLogger(__name__)
ROOM_ID = 1


class GameServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, store, policy):
        self.store, self.policy = store, policy
        self.startup = StartupServices()
        self.inventory = InventoryServices(store)
        # Native movement notifications use a one-byte room user ID.
        self.available_ids = set(range(1, 256))
        self.world_sessions = {}
        self.lock = threading.Lock()
        self.connections = set()
        self.slots = threading.BoundedSemaphore(32)
        super().__init__(address, GameHandler)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        with self.lock:
            self.connections.add(request)
        try:
            super().process_request(request, address)
        except Exception:
            with self.lock:
                self.connections.discard(request)
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            with self.lock:
                self.connections.discard(request)
            self.slots.release()

    def server_close(self):
        with self.lock:
            connections = list(self.connections)
        for connection in connections:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        super().server_close()

    def handle_error(self, request, address):
        # Exceptions can contain session input; keep tracebacks out of device logs.
        LOG.error("TCP internal error; check the local database and server installation")


class GameHandler(socketserver.BaseRequestHandler):
    def send(self, payload):
        self.request.sendall(wire.frame(payload))

    def emit(self, name, payload, room=False):
        self.send(wire.event(name, payload, room=room))

    def handle(self):
        self.request.settimeout(15)
        self.player = None
        self.joined = False
        self.world = None
        started = time.monotonic()
        opcode, name = None, None
        with self.server.lock:
            self.transport_id = min(self.server.available_ids)
            self.server.available_ids.remove(self.transport_id)
        try:
            first = wire.receive(self.request)
            if first[0] not in (wire.CONNECT, wire.RECONNECT):
                raise wire.ProtocolError("Expected Connect/Reconnect")
            if first[0] == wire.CONNECT and len(first) != 1:
                raise wire.ProtocolError("Invalid Connect")
            if len(first) > 257:
                raise wire.ProtocolError("Invalid Reconnect key")
            # A transport key is never sufficient to authorize a persisted account.
            key = secrets.token_hex(16).encode("ascii")
            self.send(bytes((3,)) + wire.I32.pack(self.transport_id) + key)
            LOG.info("TCP connected; waiting for game login")
            while True:
                opcode, name = None, None
                packet = wire.receive(self.request)
                opcode = packet[0]
                if opcode in (wire.PING, wire.PONG):
                    if len(packet) != 1:
                        raise wire.ProtocolError("Invalid keepalive")
                    if opcode == wire.PING:
                        self.send(bytes((wire.PONG,)))
                elif opcode in (wire.EVENT, wire.ROOM_EVENT):
                    name, payload = wire.parse_event(packet)
                    if opcode == wire.EVENT and name == "login":
                        if not self.login(payload):
                            break
                    elif self.player is None:
                        raise wire.ProtocolError("Game login required")
                    elif opcode == wire.ROOM_EVENT and name == "profile_update":
                        if not self.joined:
                            raise wire.ProtocolError("Room required")
                        self.profile(payload)
                    elif opcode == wire.ROOM_EVENT and name == "tbulv":
                        if not self.joined:
                            raise wire.ProtocolError("Room required")
                        self.cosmetic(payload)
                    elif opcode == wire.ROOM_EVENT and name == "equip":
                        if not self.joined:
                            raise wire.ProtocolError("Room required")
                        self.equip(payload)
                    elif opcode == wire.ROOM_EVENT and name == "backpack":
                        if not self.joined:
                            raise wire.ProtocolError("Room required")
                        response = self.server.inventory.backpack(payload, player_id=self.player["id"])
                        if response is not None:
                            self.emit("backpack", response, room=True)
                    elif opcode == wire.ROOM_EVENT and name in WORLD_REQUESTS:
                        if not self.joined:
                            raise wire.ProtocolError("Room required")
                        responses = self.world.handle(name, payload)
                        if responses is None:
                            LOG.info("TCP unsupported world request name=%s", json.dumps(name))
                        else:
                            for response_name, response_payload in responses:
                                self.emit(response_name, response_payload, room=True)
                    elif opcode == wire.ROOM_EVENT and name in REQUESTS:
                        if not self.joined:
                            raise wire.ProtocolError("Room required")
                        responses = self.server.startup.handle(name, payload,
                            user_id=self.player["user_id"], transport_id=self.transport_id)
                        if responses is None:
                            LOG.info("TCP unsupported event opcode=%d name=%s bytes=%d",
                                     opcode, json.dumps(name), len(payload))
                        else:
                            for response_name, response_payload in responses:
                                self.emit(response_name, response_payload, room=True)
                    else:
                        # Event names are user input: report a bounded, escaped name only.
                        LOG.info("TCP unsupported event opcode=%d name=%s bytes=%d",
                                 opcode, json.dumps(name[:64]), len(payload))
                elif opcode in (wire.JOIN, wire.LEAVE):
                    if self.player is None or len(packet) != 5:
                        raise wire.ProtocolError("Invalid room request")
                    if wire.I32.unpack(packet[1:])[0] != ROOM_ID:
                        raise wire.ProtocolError("Unknown local world room")
                    if opcode == wire.JOIN:
                        self.join()
                    else:
                        self.leave()
                        self.send(bytes((7,)) + wire.I32.pack(ROOM_ID))
                else:
                    raise wire.ProtocolError("Unsupported opcode")
        except EOFError:
            LOG.info("TCP disconnected")
        except TimeoutError:
            LOG.info("TCP timed out waiting for client data")
        except wire.ProtocolError as error:
            # ProtocolError messages are fixed validation labels, without payloads.
            LOG.info("TCP rejected packet opcode=%s event=%s reason=%s",
                     opcode, json.dumps(name[:64]) if name else "none", str(error))
        except struct.error:
            LOG.info("TCP rejected packet opcode=%s event=%s reason=Invalid integer encoding",
                     opcode, json.dumps(name[:64]) if name else "none")
        except OSError:
            LOG.info("TCP connection closed")
        finally:
            if self.world is not None:
                LOG.info("TCP world session ended; positionReceived=%s movementPackets=%d durationSeconds=%d",
                         str(self.world.position is not None).lower(), self.world.movement_packets,
                         int(time.monotonic() - started))
            self.leave()
            with self.server.lock:
                self.server.available_ids.add(self.transport_id)

    def leave(self):
        self.joined = False
        with self.server.lock:
            self.server.world_sessions.pop(self.transport_id, None)
        self.world = None

    def login(self, payload):
        request = wire.Proto(payload)
        if self.player is not None:
            raise wire.ProtocolError("Already logged in")
        try:
            if not self.server.policy.enabled or request.text(3) != self.server.policy.app_version:
                raise AccountError("VERSION_DISABLED", "This local server accepts PK XD 1.38.4 only.")
            self.player = self.server.store.user(request.text(1))
        except AccountError:
            self.emit("login", wire.string(2, "Invalid local session or unsupported app version."))
            LOG.info("TCP login rejected: invalid local session or app version")
            return False
        is_new = not self.player["character_created"]
        self.emit("login", wire.number(1, True) + wire.number(3, is_new) + wire.number(4, is_new))
        self.request.settimeout(120)
        LOG.info("TCP login accepted; newCharacter=%s", str(is_new).lower())
        self.join()
        return True

    def join(self):
        if self.joined:
            return
        self.joined = True
        # One isolated local world per connection; no shared-room broadcasts yet.
        self.world = LocalWorldSession(self.player["user_id"], self.transport_id)
        with self.server.lock:
            self.server.world_sessions[self.transport_id] = self.world
        self.send(bytes((6, 1)) + wire.I32.pack(ROOM_ID) + wire.I32.pack(self.transport_id))
        self.bootstrap()
        LOG.info("TCP character bootstrap sent")
        LOG.info("TCP local world room joined; waiting for client scene and position")

    def set_variable(self, key, value, *, global_variable=False):
        self.emit("tbugv" if global_variable else "tbulv",
                  wire.variable(self.transport_id, key, value), room=not global_variable)

    def bootstrap(self):
        player = self.server.store.player(self.player["id"])
        inventory = self.server.store.inventory(player["id"])
        # Inventory.InitInventory consumes alternating item IDs and quantities.
        inventory_data = b"".join(wire.I32.pack(item_id) + wire.I32.pack(quantity)
                                  for item_id, quantity in inventory.items())
        values = {
            "k": b"\x01" + player["user_id"].encode(),
            "m": b"\x01" + player["nickname"].encode(),
            "p": b"\x06" + inventory_data,
            "o": b"\x06" + b"".join(wire.I32.pack(item) for item in DEFAULT_EQUIPPED_ITEMS),
            "wa": b"\x05",                # ByteList containing empty protobuf Money (all zero).
            "j": b"\x05\xd9\xa0\x79",  # ByteList, three RGB bytes; local default.
            "s": b"\x05",                 # Empty ByteList HouseData; no house service yet.
            "i": b"\x03\x00",           # ByteVariable slot, local bootstrap slot zero.
            "hs": b"\x02" + wire.I32.pack(0),
        }
        values.update({k: bytes.fromhex(v) for k, v in json.loads(player["cosmetics"]).items()
                       if not (k == "o" and v == "06")})
        values.update(INITIAL_VARIABLES)
        for key, value in values.items():
            self.set_variable(key, value)
        for key in ("k", "m"):
            self.set_variable(key, values[key], global_variable=True)
        LOG.info("TCP initial inventory sent entries=%d equippedSlots=%d", len(inventory), (len(values["o"]) - 1) // 4)

    def cosmetic(self, payload):
        # UserVariable.Serialize (0x3A86404) omits UserId on client writes.
        # Server notifications add it back for UserVariable.Deserialize.
        key, value = wire.parse_client_variable_update(payload)
        if self.world.set_runtime_variable(key, value):
            self.set_variable(key, value)
            LOG.info("TCP world runtime variable updated key=%s", json.dumps(key))
            return
        valid = ((key == "j" and len(value) == 4 and value[0] == 5)
                 or (key == "hs" and len(value) == 5 and value[0] == 2
                     and 0 <= wire.I32.unpack(value[1:])[0] <= 1000000)
                 or (key == "o" and value[0] == 6 and (len(value) - 1) % 4 == 0
                     and len(value) <= 1 + 32 * 4
                     and all(0 <= item[0] <= 1000000 for item in struct.iter_unpack(">i", value[1:]))))
        if not valid:
            LOG.info("TCP user variable rejected key=%s type=%d bytes=%d",
                     json.dumps(key) if len(key) <= 4 else "unknown", value[0], len(value))
            return
        self.server.store.save_cosmetic(self.player["id"], key, value)
        self.set_variable(key, value)
        LOG.info("TCP character appearance saved")

    def equip(self, payload):
        # SendEquipMessage emits this protobuf, then observes variable changes.
        request = wire.Proto(payload)
        items = request.integers(1)
        color = request.message(2)
        rgb = [color.integer(field) for field in (1, 2, 3)]
        hair_style = request.integer(4)
        if (not 4 <= len(items) <= 32 or any(item > 1000000 for item in items)
                or any(channel > 255 for channel in rgb) or hair_style > 1000000):
            raise wire.ProtocolError("Invalid appearance")
        values = {"o": b"\x06" + b"".join(wire.I32.pack(item) for item in items),
                  "j": b"\x05" + bytes(rgb), "hs": b"\x02" + wire.I32.pack(hair_style)}
        self.server.store.save_cosmetics(self.player["id"], values)
        for key, value in values.items():
            self.set_variable(key, value)
        LOG.info("TCP character appearance saved (equip)")

    def profile(self, payload):
        request = wire.Proto(payload)
        event_id = request.integer(1)
        LOG.info("TCP profile request id=%d", event_id)
        player = self.server.store.player(self.player["id"])
        if event_id == 0:  # SetNicknameRequest; proto3 omits the default event ID.
            try:
                name = self.server.store.set_name(player["id"], request.text(2))
            except AccountError as error:
                self.emit("set_name_result", wire.string(2, str(error)), room=True)
                LOG.info("TCP character name rejected: %s", error.code)
            else:
                self.emit("set_name_result", wire.string(1, name), room=True)
                self.set_variable("m", b"\x01" + name.encode())
                self.set_variable("m", b"\x01" + name.encode(), global_variable=True)
                LOG.info("TCP character name saved")
        elif event_id == 12:
            self.emit("default_nickname_result", wire.string(1, player["nickname"]), room=True)
        elif event_id == 10:
            self.emit("account_created_date", wire.number(1, True) + wire.number(3, player["created_at"]), room=True)
        elif event_id in (4, 5):
            error_message = ""
            if event_id == 4:
                try:
                    self.server.store.set_legal(player["id"], request.text(2), bool(request.integer(3)))
                except AccountError as error:
                    error_message = str(error)
                player = self.server.store.player(player["id"])
            # No acceptance is inferred from connecting or creating an anonymous identity.
            # LatestTermsVersion is empty until a local terms document is configured.
            response = (wire.number(1, not error_message) + wire.string(2, error_message)
                        + wire.string(3, "SET" if event_id == 4 else "GET")
                        + wire.string(4, player["terms"]) + wire.number(6, player["ads_consent"]))
            self.emit("Q", response, room=True)
            LOG.info("TCP legal information sent action=%s", "SET" if event_id == 4 else "GET")
        elif event_id in (6, 7):
            if event_id == 6:
                self.server.store.set_open_chat(player["id"], bool(request.integer(2)))
                player = self.server.store.player(player["id"])
            response = (wire.number(1, True) + wire.string(3, "SET" if event_id == 6 else "GET")
                        + wire.number(4, player["open_chat"]))
            self.emit("R", response, room=True)
        else:
            LOG.info("TCP unsupported profile event id=%d", event_id)
