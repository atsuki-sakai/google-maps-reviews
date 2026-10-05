"""Launch and close only the CLI's dedicated local Chrome process."""
from __future__ import annotations

import fcntl
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path


def browser_executable(pw, browser: str) -> Path:
    if browser == "chromium":
        executable = Path(pw.chromium.executable_path)
    else:
        candidates = [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                      Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
        executable = next((path for path in candidates if path.is_file()), candidates[0])
    if not executable.is_file():
        raise RuntimeError(f"ブラウザーが見つかりません。google-maps-reviews setup --browser {browser} を実行してください。")
    return executable


@contextmanager
def collection_browser(pw, browser: str):
    profile = Path.home() / "Library" / "Application Support" / "google-maps-reviews" / browser
    profile.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (profile / ".collector.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("この専用ブラウザーでは収集中です。完了してから再実行してください。") from None
        port_file = profile / "DevToolsActivePort"
        port_file.unlink(missing_ok=True)
        process = None
        connection = None
        try:
            process = subprocess.Popen([
                str(browser_executable(pw, browser)), f"--user-data-dir={profile}",
                "--remote-debugging-port=0", "--remote-debugging-address=127.0.0.1",
                "--no-first-run", "--no-default-browser-check", "--window-size=1280,900", "about:blank",
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError("専用ブラウザーを起動できません。前回の専用ブラウザーを閉じて再実行してください。")
                try:
                    port = int(port_file.read_text().splitlines()[0])
                    if 0 < port <= 65535:
                        break
                except (OSError, ValueError, IndexError):
                    pass
                time.sleep(0.1)
            else:
                raise RuntimeError("専用ブラウザーの起動が時間切れになりました。再実行してください。")
            connection = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}", timeout=15000)
            yield connection.contexts[0]
        finally:
            if connection:
                try:
                    connection.close()
                except Exception:
                    pass
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
