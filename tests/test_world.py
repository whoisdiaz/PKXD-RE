import math
import struct
import unittest

from pkxd_server import wire
from pkxd_server.world import LocalWorldSession


class WorldContractTests(unittest.TestCase):
    def setUp(self):
        self.world = LocalWorldSession("local-player", 7)

    def test_native_position_and_layer_formats_are_distinct_from_server_snapshots(self):
        # GetPositionStateObject 0x2DE3004: teleport byte + sequence + 4 BE floats.
        position = bytes.fromhex("01ff3f800000400000004040000042b40000")
        self.assertEqual(len(position), 18)
        self.assertEqual(self.world.handle("C", position), [])
        self.assertEqual((self.world.teleported, self.world.sequence, self.world.position),
                         (True, 255, (1., 2., 3., 90.)))
        # GetLayerObject 0x2DE3194: BE int layer + sequence + 4 BE floats.
        layer = bytes.fromhex("00000064003f800000400000004040000042b40000")
        self.assertEqual(len(layer), 21)
        self.assertEqual(self.world.handle("PL", layer), [])
        self.assertEqual((self.world.layer, self.world.sequence), (100, 0))
        self.assertEqual(self.world.variables["A"], bytes.fromhex("0200000064"))

    def test_malformed_movement_cannot_change_world_state(self):
        for name, value in (("C", b""), ("C", bytes(17)), ("C", bytes(19)),
                            ("C", bytes.fromhex("02") + bytes(17)),
                            ("C", struct.pack(">BBffff", 0, 1, math.nan, 0., 0., 0.)),
                            ("PL", struct.pack(">iBffff", -1, 1, 0., 0., 0., 0.)),
                            ("PL", struct.pack(">iBffff", 0, 1, 0., math.inf, 0., 0.))):
            with self.subTest(name=name, payload=value), self.assertRaises(wire.ProtocolError):
                self.world.handle(name, value)
        self.assertIsNone(self.world.position)
        self.assertEqual(self.world.movement_packets, 0)

    def test_native_empty_slot_cache_and_clean_requests(self):
        # SlotCacheRequest field 3 is the user UUID, not field 2 (an int32 ID).
        request = wire.number(1, 2) + wire.string(3, "local-player")
        self.assertEqual(self.world.handle("slot_interaction", request), [("n", b"")])
        self.assertEqual(self.world.handle("slot_interaction", wire.number(1, 3)), [])

    def test_slot_occupy_cache_free_and_zero_negative_ids(self):
        for slot in (0, -12, 55):
            request = wire.number(2, slot & ((1 << 64) - 1)) + wire.string(3, "local-player")
            responses = self.world.handle("slot_interaction", request)
            result = wire.Proto(responses[0][1])
            update = wire.Proto(responses[1][1])
            self.assertEqual((responses[0][0], result.integer(1), result.integer(2), result.text(3)),
                             ("n", 3, 1, "local-player"))
            self.assertEqual((update.integer(1), update.int32(2)), (1, slot))
        cache = wire.Proto(self.world.handle("slot_interaction", b"\x08\x02")[0][1])
        ids = [v - (1 << 64) if v & (1 << 63) else v for v in cache.integers(2)]
        self.assertEqual(ids, [-12, 0, 55])
        self.assertEqual(cache.texts(3), ["local-player"] * 3)
        removal = self.world.handle("slot_interaction", b"\x08\x01\x10\x37")[0][1]
        self.assertEqual(wire.Proto(removal).integers(2), [55])
        self.world.handle("slot_interaction", b"\x08\x03")
        self.assertEqual(self.world.slots, {})

    def test_slot_requests_cannot_impersonate_another_user(self):
        for field in (3, 4):
            with self.assertRaises(wire.ProtocolError):
                self.world.handle("slot_interaction", wire.string(field, "someone-else"))
        self.assertEqual(self.world.slots, {})

    def test_runtime_flags_have_a_separate_policy_from_inventory_and_wallet(self):
        for key in ("e", "g", "h", "hrsl", "mg", "eb"):
            self.assertTrue(self.world.set_runtime_variable(key, b"\x04\x01"))
            self.assertFalse(self.world.set_runtime_variable(key, b"\x04\x02"))
        for key in ("wa", "p", "D", "I", "k", "A"):
            self.assertFalse(self.world.set_runtime_variable(key, b"\x04\x01"))
        self.assertFalse(self.world.set_runtime_variable("he", bytes.fromhex("0200000011")))
        self.assertTrue(self.world.set_runtime_variable("he", bytes.fromhex("0200000000")))
        self.assertNotIn("h", LocalWorldSession("another-player", 8).variables)

    def test_unsupported_world_operations_stay_unsupported(self):
        self.assertIsNone(self.world.handle("slot_interaction", b"\x08\x63"))
        self.assertIsNone(self.world.handle("unknown", b""))
