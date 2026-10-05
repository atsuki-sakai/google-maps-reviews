import fcntl
import json
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from google_maps_reviews import browser


class DedicatedBrowserTest(unittest.TestCase):
    def fixture(self, folder):
        profile = Path(folder) / "Library/Application Support/google-maps-reviews/chrome"
        process = MagicMock()
        process.poll.return_value = None
        connection = MagicMock()
        context = MagicMock()
        connection.contexts = [context]
        pw = MagicMock()
        pw.chromium.connect_over_cdp.return_value = connection
        def launch(_args, **_kwargs):
            (profile / "DevToolsActivePort").write_text("43210\n/devtools/browser/test\n")
            return process
        return profile, process, connection, context, pw, launch

    def test_dedicated_profile_and_loopback_port_are_owned_and_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            profile, process, connection, context, pw, launch = self.fixture(folder)
            with patch.object(browser.Path, "home", return_value=Path(folder)), \
                    patch.object(browser, "browser_executable", return_value=Path("/test/Chrome")), \
                    patch.object(browser.subprocess, "Popen", side_effect=launch) as launching:
                with browser.collection_browser(pw, "chrome") as result:
                    self.assertIs(result, context)
                    with self.assertRaisesRegex(RuntimeError, f"実行元PID: {os.getpid()}"):
                        with browser.collection_browser(pw, "chrome"):
                            self.fail("同じプロファイルで二重起動しました")
                self.assertEqual(launching.call_count, 1)
                args = launching.call_args.args[0]
                self.assertIn(f"--user-data-dir={profile}", args)
                self.assertIn("--remote-debugging-address=127.0.0.1", args)
                self.assertIn("--remote-debugging-port=0", args)
                self.assertEqual(profile.stat().st_mode & 0o777, 0o700)
                pw.chromium.connect_over_cdp.assert_called_once_with("http://127.0.0.1:43210", timeout=15000)
                connection.close.assert_called_once()
                process.terminate.assert_called_once()
                process.wait.assert_called_once_with(timeout=5)

    def test_connection_failure_still_stops_only_the_spawned_process(self):
        with tempfile.TemporaryDirectory() as folder:
            _profile, process, _connection, _context, pw, launch = self.fixture(folder)
            pw.chromium.connect_over_cdp.side_effect = RuntimeError("接続失敗")
            with patch.object(browser.Path, "home", return_value=Path(folder)), \
                    patch.object(browser, "browser_executable", return_value=Path("/test/Chrome")), \
                    patch.object(browser.subprocess, "Popen", side_effect=launch), self.assertRaisesRegex(RuntimeError, "接続失敗"):
                with browser.collection_browser(pw, "chrome"):
                    self.fail("接続失敗後に収集しました")
            process.terminate.assert_called_once()

    def test_shutdown_timeout_kills_and_reaps_the_spawned_process(self):
        with tempfile.TemporaryDirectory() as folder:
            _profile, process, _connection, _context, pw, launch = self.fixture(folder)
            process.wait.side_effect = [subprocess.TimeoutExpired("Chrome", 5), 0]
            with patch.object(browser.Path, "home", return_value=Path(folder)), \
                    patch.object(browser, "browser_executable", return_value=Path("/test/Chrome")), \
                    patch.object(browser.subprocess, "Popen", side_effect=launch):
                with browser.collection_browser(pw, "chrome"):
                    pass
            process.kill.assert_called_once()
            self.assertEqual(process.wait.call_count, 2)

    def test_existing_lock_file_without_os_lock_does_not_block_collection(self):
        with tempfile.TemporaryDirectory() as folder:
            profile, process, _connection, context, pw, launch = self.fixture(folder)
            profile.mkdir(parents=True)
            lock = profile / ".collector.lock"
            lock.write_text('{"pid":999999,"started_at":"old"}')
            with patch.object(browser.Path, "home", return_value=Path(folder)), \
                    patch.object(browser, "browser_executable", return_value=Path("/test/Chrome")), \
                    patch.object(browser.subprocess, "Popen", side_effect=launch):
                with browser.collection_browser(pw, "chrome") as result:
                    self.assertIs(result, context)
                    self.assertEqual(json.loads(lock.read_text())["pid"], os.getpid())
            self.assertEqual(lock.read_text(), "")
            process.terminate.assert_called_once()

    def test_sigterm_closes_browser_releases_lock_and_restores_handler(self):
        # A separate process receives a real SIGTERM while holding the lock.
        # Its owned browser is a small Python sleeper, never the user's Chrome.
        script = '''
import signal, subprocess, sys, time
from pathlib import Path
from unittest.mock import MagicMock, patch
from google_maps_reviews import browser
root = Path(sys.argv[1])
profile = root / "Library/Application Support/google-maps-reviews/chrome"
native_popen = subprocess.Popen
children = []
def launch(_args, **_kwargs):
    child = native_popen([sys.executable, "-c", "import time; time.sleep(60)"])
    children.append(child)
    (profile / "DevToolsActivePort").write_text("43210\\n/devtools/browser/test\\n")
    return child
pw = MagicMock()
pw.chromium.connect_over_cdp.return_value.contexts = [MagicMock()]
previous = signal.getsignal(signal.SIGTERM)
with patch.object(browser.Path, "home", return_value=root), patch.object(browser, "browser_executable", return_value=Path("/test/Chrome")), patch.object(browser.subprocess, "Popen", side_effect=launch):
    try:
        with browser.collection_browser(pw, "chrome"):
            print(children[0].pid, flush=True)
            time.sleep(60)
    except SystemExit as error:
        print("cleaned", flush=True)
        print(signal.getsignal(signal.SIGTERM) == previous, flush=True)
        raise
print(signal.getsignal(signal.SIGTERM) == previous, flush=True)
'''
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder) / "Library/Application Support/google-maps-reviews/chrome"
            process = subprocess.Popen([sys.executable, "-u", "-c", script, folder], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            child_pid = None
            try:
                import select
                self.assertTrue(select.select([process.stdout], [], [], 5)[0], "終了処理の検証が起動しませんでした")
                child_pid = int(process.stdout.readline())
                process.terminate()
                stdout, stderr = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 128 + signal.SIGTERM, stderr)
                self.assertIn("cleaned\nTrue", stdout)
                with self.assertRaises(ProcessLookupError):
                    os.kill(child_pid, 0)
                with (profile / ".collector.lock").open("a+") as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self.assertEqual(lock.read(), "")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate(timeout=5)
                if child_pid:
                    try:
                        os.kill(child_pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass


if __name__ == "__main__":
    unittest.main()
