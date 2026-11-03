import unittest

from pkxd_server import wire
from pkxd_server.animation import valid_animation
from pkxd_server.world import LocalWorldSession


# Synthetic fixture built from the recovered schema, not captured from Android.
# Five nonnull animation messages, LE float32 values, and int32 Animator hashes.
ANIMATION = bytes.fromhex(
    "05"
    "0a1608ffffffff0710ffffffff071d0000003f250000803f"
    "120e080110021d0000003f250000803f"
    "1a0e080110021d0000003f250000803f"
    "220e080110021d0000003f250000803f"
    "2a0e080110021d0000003f250000803f"
    "30013802")


class AnimationContractTests(unittest.TestCase):
    def test_native_byte_list_with_five_animation_objects_is_transient(self):
        self.assertEqual(len(ANIMATION), 93)
        self.assertTrue(valid_animation(ANIMATION))
        world = LocalWorldSession("local-player", 7)
        self.assertTrue(world.set_runtime_variable("aaa", ANIMATION))
        self.assertEqual(world.variables["aaa"], ANIMATION)
        self.assertEqual(world.animation_updates, 1)
        self.assertNotIn("aaa", LocalWorldSession("local-player", 8).variables)

    def test_present_empty_messages_and_negative_hashes_match_csharp_schema(self):
        self.assertTrue(valid_animation(bytes.fromhex("050a0012001a0022002a00")))
        # C# protobuf int32 -1 uses a ten-byte varint.
        negative = bytes.fromhex("08ffffffffffffffffff01")
        body = wire.blob(1, negative) + b"".join(wire.blob(field, b"") for field in range(2, 6))
        self.assertTrue(valid_animation(b"\x05" + body))

    def test_truncation_types_nonfinite_floats_and_absent_submessages_are_rejected(self):
        empty = bytes.fromhex("050a0012001a0022002a00")
        invalid = (b"", b"\x05", b"\x01" + empty[1:], empty[:-2],
                   b"\x05\x08\x01" + empty[3:], ANIMATION[:-1], ANIMATION + b"\x30\x02",
                   ANIMATION.replace(bytes.fromhex("1d0000003f"), bytes.fromhex("1d0000c07f"), 1),
                   ANIMATION + b"\x05" * 4096)
        for value in invalid:
            with self.subTest(payload=value):
                self.assertFalse(valid_animation(value))

    def test_duplicate_message_fields_cannot_hide_invalid_merged_data(self):
        # Protobuf merges repeated occurrences of singular message fields.
        # Validate all occurrences, not just the last animation message.
        invalid_first = wire.blob(1, bytes.fromhex("1d0000c07f"))
        empty_five = bytes.fromhex("0a0012001a0022002a00")
        self.assertFalse(valid_animation(b"\x05" + invalid_first + empty_five))
        world = LocalWorldSession("local-player", 7)
        self.assertFalse(world.set_runtime_variable("aaa", b"\x05" + invalid_first + empty_five))
        self.assertNotIn("aaa", world.variables)
