import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest

from tools.capture_android_startup import MAX_CAPTURE, capture, read_capture, redact


class AndroidCaptureTests(unittest.TestCase):
    def test_redaction_preserves_exception_and_asset_path(self):
        log = ('Unity E [GameController] Game initialization failed: NullReferenceException\n'
               'https://name:password@example.test/assets/world.bundle?token=private-value#secret\n'
               'authToken="private-token" Bearer private-bearer\n'
               'https://example.test/v1/auth/sessions/private-path-token\n'
               'userToken=private-user-token sessionId: private-session\n'
               '12345678-1234-1234-1234-123456789012\n')
        clean = redact(log)
        for value in ("password", "private-value", "private-token", "private-bearer", "private-user-token", "private-session", "private-path-token", "12345678-1234"):
            self.assertNotIn(value, clean)
        self.assertIn("NullReferenceException", clean)
        self.assertIn("example.test/assets/world.bundle", clean)

    def test_bounded_capture_keeps_start_and_end(self):
        with tempfile.TemporaryFile() as stream:
            stream.write(b"FIRST\n" + b"x" * (MAX_CAPTURE * 2) + b"\nLAST\n")
            text = read_capture(stream)
        self.assertTrue(text.startswith("FIRST"))
        self.assertTrue(text.endswith("LAST\n"))
        self.assertIn("truncada", text)
        self.assertLess(len(text), MAX_CAPTURE + 100)

    def fake_adb(self, root, *, wait=False, missing_pid=False):
        script = root / "fake_adb.py"
        script.write_text(
            "import sys,time\n"
            "args=sys.argv[1:]\n"
            "if args[:2]==['shell','pidof']:\n"
            " assert args[2]=='com.movile.playkids.pkxd'\n"
            + (" sys.exit(1)\n" if missing_pid else " print('321')\n")
            + "else:\n"
            " assert args==['logcat','-T','1','--pid','321','-v','threadtime','Unity:E','AndroidRuntime:E','*:S']\n"
            " print('Unity E [GameController] Game initialization failed: NullReferenceException',flush=True)\n"
            " print('Unity E userToken=private-capture-token',flush=True)\n"
            + (" time.sleep(10)\n" if wait else ""), encoding="utf-8")
        return [sys.executable, str(script)]

    def test_command_filters_pid_and_error_tags_and_saves_sanitized_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "data" / "startup.txt"
            console = io.StringIO()
            with contextlib.redirect_stdout(console):
                capture(self.fake_adb(root), 1, output)
            self.assertIn("NullReferenceException", output.read_text())
            self.assertNotIn("private-capture-token", output.read_text() + console.getvalue())

    def test_timeout_saves_errors_already_received(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "startup.txt"
            with contextlib.redirect_stdout(io.StringIO()):
                capture(self.fake_adb(root, wait=True), 1, output)
            self.assertIn("NullReferenceException", output.read_text())

    def test_missing_app_process_does_not_collect_another_apps_logs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "startup.txt"
            with self.assertRaises(ValueError):
                capture(self.fake_adb(root, missing_pid=True), 1, output)
            self.assertFalse(output.exists())
