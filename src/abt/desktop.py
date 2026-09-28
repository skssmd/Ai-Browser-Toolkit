"""`abt app`: the desktop window.

The window is a pywebview shell around the server's own `/app` page. The shell
exists for one reason beyond being a window: it can read the owner-only token
files and hand them to the page through pywebview's JS bridge, so the operator
token and sealed-session tokens never travel over HTTP and never sit in the
page's source.

Without pywebview installed the page opens in the default browser instead, and
asks for the operator token once.
"""

from __future__ import annotations

import webbrowser
from pathlib import Path

import httpx

from .profiles import check_name


class Bridge:
    """What the page may ask the shell for. Exposed as `window.pywebview.api`."""

    def __init__(self, sessions_dir: Path) -> None:
        self._dir = Path(sessions_dir)

    def _read(self, name: str) -> str | None:
        try:
            return (self._dir / name).read_text(encoding="utf-8").strip() or None
        except OSError:
            return None

    def operator_token(self) -> str | None:
        return self._read("operator.token")

    def session_token(self, name: str) -> str | None:
        try:
            check_name(name, "session")
        except Exception:
            return None
        return self._read(f"{name}.token")


def sessions_dir(base: str) -> Path | None:
    """Ask the running server where its token files are.

    Asked rather than computed: the server may have been started from another
    directory, and a checkout and an installed copy keep them in different
    places.
    """
    try:
        body = httpx.get(f"{base}/app/where", timeout=5).json()
    except Exception:
        return None
    if not body.get("ok"):
        return None
    return Path(body["result"]["sessions_dir"])


def open_window(base: str, width: int = 1440, height: int = 900) -> str:
    """Show the app. Returns how: "window" or "browser"."""
    where = sessions_dir(base)
    url = f"{base}/app"
    try:
        import webview  # pywebview
    except ImportError:
        webbrowser.open(url)
        return "browser"
    api = Bridge(where) if where is not None else None
    webview.create_window(
        "AI Browser Toolkit", url, js_api=api, width=width, height=height, min_size=(900, 600)
    )
    # pywebview starts in private mode by default, which wipes the page's
    # storage when the window closes -- so every launch forgot the chat you
    # were in, the theme and the chat panel's side and width.
    storage = str(where / "app-window") if where is not None else None
    webview.start(private_mode=False, storage_path=storage)
    # The window is closed. Its browsers run hidden, so nothing else would
    # ever close them: ask the server to. The server itself stays up.
    close_browsers(base, api)
    return "window"


def close_browsers(base: str, api: "Bridge | None") -> None:
    token = api.operator_token() if api is not None else None
    if not token:
        return
    try:
        httpx.post(f"{base}/app/quit", headers={"X-ABT-Token": token}, timeout=30)
    except Exception:
        pass
