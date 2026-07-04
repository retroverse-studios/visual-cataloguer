"""Desktop entry point — a native window around the local web UI.

Runs the existing FastAPI app on a free localhost port in a background
thread and opens a pywebview window pointing at it. Used by the
``viscatalog desktop`` CLI command and as the PyInstaller entry point
for the packaged desktop builds (see packaging/).

Unlike ``viscatalog serve`` (which defaults to ./collection.db), the
desktop app stores its database in the platform's per-user data
directory so double-clicking the app always finds the same collection
regardless of working directory.
"""

from __future__ import annotations

import argparse
import socket
import sys
import threading
import time
from pathlib import Path

APP_NAME = "visual-cataloguer"
WINDOW_TITLE = "Visual Cataloguer"


def _ensure_streams() -> None:
    """Give Python real stdout/stderr in windowed builds.

    PyInstaller's console=False bootloader leaves sys.stdout/sys.stderr as
    None (most visibly on Windows), so the first print() or logging emit
    crashes the app. Route them to a log file next to the database instead.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return
    log_path = default_database_path().parent / "desktop.log"
    stream = open(log_path, "a", buffering=1, encoding="utf-8", errors="replace")  # noqa: SIM115
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


def default_database_path() -> Path:
    """Per-user data location for the desktop database."""
    import platformdirs

    data_dir = Path(platformdirs.user_data_dir(APP_NAME, appauthor=False))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "collection.db"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_server(database: Path, port: int) -> threading.Thread:
    """Start uvicorn serving the app on 127.0.0.1:port in a daemon thread."""
    import uvicorn

    from cataloguer.api.app import app
    from cataloguer.api.deps import configure_database

    configure_database(database)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True, name="viscatalog-server")
    thread.start()
    return thread


def _wait_for_server(url: str, timeout: float = 30.0) -> None:
    import httpx

    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{url}/api/health", timeout=2.0).status_code == 200:
                return
        except httpx.HTTPError as e:
            last_error = e
        time.sleep(0.2)
    raise RuntimeError(f"Server did not start within {timeout}s: {last_error}")


def run(database: Path | None = None, no_gui: bool = False, port: int | None = None) -> None:
    """Start the local server and (unless no_gui) open the app window."""
    db_path = (database or default_database_path()).absolute()
    server_port = port or _free_port()
    url = f"http://127.0.0.1:{server_port}"

    _start_server(db_path, server_port)
    _wait_for_server(url)

    if no_gui:
        print(f"Database: {db_path}")
        print(f"Serving at {url} (Ctrl+C to stop)")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return
        return

    import webview

    webview.create_window(WINDOW_TITLE, url, width=1280, height=860, min_size=(900, 600))
    # Blocks until the window is closed; the daemon server thread dies with us.
    webview.start()


def main() -> None:
    """Argparse wrapper so the frozen desktop binary accepts basic flags."""
    _ensure_streams()
    parser = argparse.ArgumentParser(prog=WINDOW_TITLE)
    parser.add_argument(
        "--database",
        type=Path,
        default=None,
        help="SQLite database path (default: per-user app data directory)",
    )
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="Start the local server without opening a window",
    )
    parser.add_argument("--port", type=int, default=None, help="Port (default: random free port)")
    args = parser.parse_args()
    run(database=args.database, no_gui=args.no_gui, port=args.port)


if __name__ == "__main__":
    main()
