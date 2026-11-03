import contextlib
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

from tools import enable_client_logging as tool


class ClientLoggingPatchTests(unittest.TestCase):
    def setUp(self):
        self.original = bytearray(128)
        self.original[:6] = b"\x7fELF\x02\x01"
        struct.pack_into("<H", self.original, 18, 183)
        self.original[64:68] = bytes.fromhex("e1031f2a")
        self.original = bytes(self.original)
        self.enabled = self.original[:64] + bytes.fromhex("21008052") + self.original[68:]
        fixture = patch.multiple(tool, LIB_SIZE=128, PATCH_OFFSET=64,
                                 ORIGINAL_SHA=hashlib.sha256(self.original).hexdigest(),
                                 ENABLED_SHA=hashlib.sha256(self.enabled).hexdigest())
        fixture.start()
        self.addCleanup(fixture.stop)

    def test_changes_only_boolean_argument_and_restores_exact_original(self):
        self.assertEqual(tool.transform(self.original), self.enabled)
        self.assertEqual(tool.transform(self.enabled), self.enabled)
        self.assertEqual(tool.transform(self.enabled, restore=True), self.original)
        self.assertEqual(tool.transform(self.original, restore=True), self.original)
        self.assertEqual([i for i, pair in enumerate(zip(self.original, self.enabled)) if pair[0] != pair[1]],
                         [64, 65, 66, 67])

    def test_unknown_build_architecture_and_size_are_rejected(self):
        for data in (b"", self.original[:-1], b"notelf" + self.original[6:],
                     self.original[:18] + b"\x03\x00" + self.original[20:],
                     self.original[:70] + b"x" + self.original[71:]):
            with self.subTest(data=data), self.assertRaises(ValueError):
                tool.transform(data)

    def test_existing_unknown_library_is_preserved_and_manifest_is_verifiable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            library = root / "libil2cpp.so"
            library.write_bytes(b"keep-this-library")
            with self.assertRaises(ValueError):
                tool.save_library(self.enabled, root, source="test")
            self.assertEqual(library.read_bytes(), b"keep-this-library")
            library.unlink()
            tool.save_library(self.enabled, root, source="test")
            tool.save_library(self.enabled, root, source="test")
            manifest = json.loads((root / "manifest.json").read_text())
            self.assertEqual(manifest["outputSha256"], hashlib.sha256(library.read_bytes()).hexdigest())
            self.assertEqual(manifest["patchLength"], 4)
            self.assertFalse(manifest["apkInstalledOrSignedByTool"])

    def test_apk_reading_rejects_missing_duplicate_and_wrong_sized_entries(self):
        with tempfile.TemporaryDirectory() as temp:
            apk = Path(temp) / "game.apk"
            with zipfile.ZipFile(apk, "w") as z:
                z.writestr(tool.LIB_ENTRY, self.original)
            self.assertEqual(tool.read_apk(apk), self.original)
            with zipfile.ZipFile(apk, "w") as z:
                z.writestr("assets/other", "x")
            self.assertIsNone(tool.read_apk(apk))
            with zipfile.ZipFile(apk, "w") as z:
                z.writestr(tool.LIB_ENTRY, "wrong size")
            with self.assertRaises(ValueError):
                tool.read_apk(apk)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with zipfile.ZipFile(apk, "w") as z:
                    z.writestr(tool.LIB_ENTRY, self.original)
                    z.writestr(tool.LIB_ENTRY, self.original)
            with self.assertRaises(ValueError):
                tool.read_apk(apk)

    def test_cli_refuses_to_overwrite_input_library(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "libil2cpp.so"
            source.write_bytes(self.original)
            with patch.object(sys, "argv", ["enable_client_logging.py", "--library", str(source), "--output-dir", str(root)]):
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    tool.main()
            self.assertEqual(source.read_bytes(), self.original)

    def test_device_extraction_prefers_arm64_split_and_does_not_install_anything(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            apk = root / "split.apk"
            with zipfile.ZipFile(apk, "w") as z:
                z.writestr(tool.LIB_ENTRY, self.original)
            fake = root / "adb.py"
            fake.write_text(
                "import sys,shutil\n"
                "args=sys.argv[1:]\n"
                "if args==['shell','pm','path','com.movile.playkids.pkxd']:\n"
                " print('package:/data/app/test/base.apk')\n"
                " print('package:/data/app/test/split_config.arm64_v8a.apk')\n"
                "else:\n"
                " assert args[:2]==['pull','/data/app/test/split_config.arm64_v8a.apk']\n"
                f" shutil.copyfile({str(apk)!r},args[2])\n")
            with contextlib.redirect_stdout(io.StringIO()):
                data, name = tool.read_device([sys.executable, str(fake)])
            self.assertEqual((data, name), (self.original, "split_config.arm64_v8a.apk"))
