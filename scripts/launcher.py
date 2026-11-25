"""Launcher used by start.bat.

Keeps all port / host / browser logic in Python so the batch file stays small.
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


def open_browser_when_ready(base_url: str) -> None:
    if os.environ.get("NO_BROWSER") == "1":
        return
    for _ in range(120):
        if probe(base_url):
            webbrowser.open(base_url + "/")
            return
        time.sleep(0.5)
    print(f"[WARN] Server did not become ready at {base_url}.")
    print("[WARN] Open that address manually in your browser.")


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

    threading.Thread(
        target=open_browser_when_ready, args=(base_url,), daemon=True
    ).start()

    import uvicorn

    try:
        uvicorn.run("main:app", host=host, port=settings.app_port)
    except KeyboardInterrupt:
        print()
        print("[INFO] Server stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
