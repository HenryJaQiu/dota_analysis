"""Launcher used by start.bat.

Starts uvicorn in a worker thread, opens the browser, and keeps the console
available for an explicit Q + Enter exit command.
"""

import os
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SETTINGS_PATH = "/api/llm/settings"
_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def probe(base_url: str, timeout: float = 1.0) -> bool:
    try:
        with _NO_PROXY.open(base_url + SETTINGS_PATH, timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False


def wait_for_start(server, thread: threading.Thread, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if server.started:
            return True
        if not thread.is_alive():
            return False
        time.sleep(0.1)
    return bool(server.started)


def wait_for_quit() -> None:
    print()
    print("=" * 58)
    print("  输入 Q 后按回车退出服务  |  Type Q + Enter to stop")
    print("  Ctrl+C 也可以退出          |  Ctrl+C also works")
    print("=" * 58)
    while True:
        try:
            command = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return
        if command in {"q", "quit", "exit", "0", "退出"}:
            return


def main() -> int:
    from app.config import settings

    host = settings.app_host or "127.0.0.1"
    display_host = "127.0.0.1" if host in {"0.0.0.0", "::", ""} else host
    base_url = f"http://{display_host}:{settings.app_port}"

    if probe(base_url):
        print(f"[INFO] The application is already running: {base_url}")
        if os.environ.get("NO_BROWSER") != "1":
            webbrowser.open(base_url + "/")
        return 0

    print(f"[INFO] Local address: {base_url}")
    print("[INFO] First load may take a few seconds.")
    print()

    import uvicorn

    config = uvicorn.Config(
        "main:app",
        host=host,
        port=settings.app_port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    server_thread = threading.Thread(target=server.run, name="uvicorn", daemon=True)
    server_thread.start()

    if not wait_for_start(server, server_thread):
        print("[ERROR] Server failed to start. Is the port already in use?")
        server.should_exit = True
        server_thread.join(timeout=3)
        return 1

    print(f"[INFO] Server ready: {base_url}")
    if os.environ.get("NO_BROWSER") != "1":
        webbrowser.open(base_url + "/")

    if os.environ.get("NO_EXIT_PROMPT") == "1":
        try:
            server_thread.join()
        except KeyboardInterrupt:
            pass
    else:
        wait_for_quit()

    print()
    print("[INFO] Shutting down, please wait...")
    server.should_exit = True
    server_thread.join(timeout=15)
    if server_thread.is_alive():
        server.force_exit = True
        server_thread.join(timeout=5)
    print("[INFO] Server stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
