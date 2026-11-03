import hashlib
import struct
import unittest
from unittest.mock import patch

from tools import redirect_lobby_metadata as redirect


class MetadataRedirectTests(unittest.TestCase):
    def setUp(self):
        # Small structural fixture. Only the input checksum is substituted; all
        # offset, overlap, length and preservation checks execute normally.
        values = list(redirect.LOBBY_LITERALS + redirect.ACCOUNT_LITERALS) + [b"keep-this-other-literal"]
        self.values = values
        records = bytearray()
        data = bytearray()
        for value in values:
            records += struct.pack("<Ii", len(value), len(data))
            data += value
        header = bytearray(256)
        struct.pack_into("<II", header, 0, 0xFAB11BAF, 29)
        struct.pack_into("<IIII", header, 8, 256, len(records), 256 + len(records), len(data))
        self.original = bytes(header + records + data)

    def transform(self, original=None, url="http://127.0.0.1:8080"):
        original = self.original if original is None else original
        with patch.object(redirect, "ORIGINAL_SHA256", hashlib.sha256(original).hexdigest()):
            return redirect.redirect_metadata(original, url)

    def test_changes_only_expected_lengths_and_literal_slots(self):
        result, changes = self.transform()
        self.assertEqual(len(result), len(self.original))
        self.assertEqual(len(changes), 2)
        allowed = set()
        for change in changes:
            allowed.update(range(change["length_offset"], change["length_offset"] + 4))
            start = change["data_offset"]
            allowed.update(range(start, start + change["old_length"]))
            length = struct.unpack_from("<I", result, change["length_offset"])[0]
            self.assertEqual(result[start:start + length], b"http://127.0.0.1:8080")
        actual = {i for i, (before, after) in enumerate(zip(self.original, result)) if before != after}
        self.assertLessEqual(actual, allowed)
        self.assertTrue(result.endswith(self.values[-1]))

    def test_unrecognized_input_is_rejected_before_using_offsets(self):
        with self.assertRaisesRegex(ValueError, "does not match"):
            redirect.redirect_metadata(self.original, "http://127.0.0.1:8080")

    def test_invalid_urls_and_long_replacements_are_rejected(self):
        for url in ["file:///tmp/lobby", "http://user:pass@localhost", "http://localhost/path",
                    "http://localhost?x=1", "http://localhost#x", "http://localhost:bad",
                    "https://this-hostname-is-longer-than-the-original.example"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.transform(url=url)

    def test_overlapping_unrelated_literal_is_rejected(self):
        malformed = bytearray(self.original)
        struct.pack_into("<Ii", malformed, 256 + 16, 5, 0)
        with self.assertRaisesRegex(ValueError, "overlaps"):
            self.transform(original=bytes(malformed))

    def test_accounts_are_opt_in_and_only_three_hosts_change(self):
        old, changes = self.transform()
        self.assertEqual(len(changes), 2)
        self.assertIn(redirect.ACCOUNT_LITERALS[0], old)
        with patch.object(redirect, "ORIGINAL_SHA256", hashlib.sha256(self.original).hexdigest()):
            result, changes = redirect.redirect_metadata(self.original, "http://127.0.0.1:8080", include_accounts=True)
        self.assertEqual(len(changes), 3)
        self.assertNotIn(redirect.ACCOUNT_LITERALS[0], result)
        self.assertEqual(len(result), len(self.original))
        self.assertTrue(result.endswith(self.values[-1]))

    def test_out_of_range_literal_is_rejected(self):
        malformed = bytearray(self.original)
        struct.pack_into("<Ii", malformed, 256, 1000000, 0)
        with self.assertRaisesRegex(ValueError, "range"):
            self.transform(original=bytes(malformed))


if __name__ == "__main__":
    unittest.main()
