import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest

from tools.capture_android_startup import MAX_CAPTURE, capture, focus_capture, read_capture, redact


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

    def test_tail_clipping_cannot_drop_credential_label_and_expose_value(self):
        with tempfile.TemporaryFile() as stream:
            stream.write(b"x" * (MAX_CAPTURE * 2) + b"\nuserToken=TOP-SECRET\n")
            stream.write(b"y" * (MAX_CAPTURE // 2 - len(b"TOP-SECRET\n")))
            text = read_capture(stream)
        self.assertNotIn("TOP-SECRET", text)

    def fake_adb(self, root, *, wait=False, missing_pid=False, empty=False, changed_pid=False, errors_only=False, reader_failure=False):
        script = root / "fake_adb.py"
        filters = ["Unity:E", "AndroidRuntime:E", "*:S"] if errors_only else ["*:V"]
        expected = ['logcat', '-T', '500', '--pid', '321', '-v', 'threadtime'] + filters
        script.write_text(
            "import sys,time\nfrom pathlib import Path\n"
            "args=sys.argv[1:]\n"
            "if args[:2]==['shell','pidof']:\n"
            " assert args[2]=='com.movile.playkids.pkxd'\n"
            + (" sys.exit(1)\n" if missing_pid else
               " marker=Path(__file__).with_suffix('.pid-seen')\n"
               + (" print('654' if marker.exists() else '321')\n" if changed_pid else " print('321')\n")
               + " marker.touch()\n")
            + "else:\n"
            + f" assert args=={expected!r}\n"
            + (" print('--------- beginning of main',flush=True)\n" if empty else
            " print('Unity E [GameController] Game initialization failed: NullReferenceException',flush=True)\n"
            " print('Unity E userToken=private-capture-token',flush=True)\n"
            " print('Unity W [InitStep] Waiting for player initialization',flush=True)\n"
            " print('Unity I [PlayerCreation] Loading local avatar',flush=True)\n")
            + (" print('adb: device offline',file=sys.stderr)\n sys.exit(1)\n" if reader_failure else "")
            + (" time.sleep(10)\n" if wait else ""), encoding="utf-8")
        return [sys.executable, str(script)]

    def test_command_filters_pid_and_keeps_warning_info_and_sanitized_errors(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "data" / "startup.txt"
            console = io.StringIO()
            with contextlib.redirect_stdout(console):
                capture(self.fake_adb(root), 1, output)
            self.assertIn("NullReferenceException", output.read_text())
            self.assertIn("Waiting for player initialization", output.read_text())
            self.assertIn("Loading local avatar", output.read_text())
            self.assertIn("mesmo processo ativo", output.read_text())
            self.assertNotIn("private-capture-token", output.read_text() + console.getvalue())

    def test_timeout_saves_errors_already_received(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "startup.txt"
            with contextlib.redirect_stdout(io.StringIO()):
                capture(self.fake_adb(root, wait=True), 1, output)
            self.assertIn("NullReferenceException", output.read_text())
            self.assertIn("janela concluída", output.read_text())

    def test_missing_app_process_does_not_collect_another_apps_logs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "startup.txt"
            with self.assertRaises(ValueError):
                capture(self.fake_adb(root, missing_pid=True), 1, output)
            self.assertFalse(output.exists())

    def test_error_only_mode_remains_available_with_history(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "startup.txt"
            with contextlib.redirect_stdout(io.StringIO()):
                capture(self.fake_adb(root, errors_only=True), 1, output, errors_only=True)
            self.assertIn("NullReferenceException", output.read_text())

    def test_focus_preserves_failure_in_middle_of_large_log(self):
        with tempfile.TemporaryFile() as stream:
            stream.write(b"normal line\n" * MAX_CAPTURE)
            stream.write(b"Unity E [GameController] Game initialization failed: MissingReferenceException\n")
            stream.write(b"Unity E at CreateLocalPlayer()\n")
            stream.write(b"normal line\n" * MAX_CAPTURE)
            self.assertNotIn("MissingReferenceException", read_capture(stream))
            focus, count, unity = focus_capture(stream)
        self.assertIn("MissingReferenceException", focus)
        self.assertIn("at CreateLocalPlayer", focus)
        self.assertEqual((count, unity), (MAX_CAPTURE * 2 + 2, 2))

    def test_empty_log_is_not_mistaken_for_successful_startup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "startup.txt"
            with contextlib.redirect_stdout(io.StringIO()):
                capture(self.fake_adb(root, empty=True), 1, output)
            self.assertIn("Nenhuma mensagem do processo foi capturada", output.read_text())
            self.assertIn("Linhas coletadas: 0", output.read_text())

    def test_changed_process_is_reported_instead_of_assuming_same_pid(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "startup.txt"
            with contextlib.redirect_stdout(io.StringIO()):
                capture(self.fake_adb(root, changed_pid=True), 1, output)
            self.assertIn("processo mudou", output.read_text())

    def test_reader_failure_still_saves_received_messages_and_reports_adb_error(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "startup.txt"
            with contextlib.redirect_stdout(io.StringIO()):
                capture(self.fake_adb(root, reader_failure=True), 1, output)
            self.assertIn("NullReferenceException", output.read_text())
            self.assertIn("status 1", output.read_text())
            self.assertIn("device offline", output.read_text())
