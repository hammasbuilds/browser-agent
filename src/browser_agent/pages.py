"""Serve the vendored MiniWoB++ pages to Chromium without opening a socket.

Every request to ``http://miniwob.local/`` is fulfilled by Playwright's router straight from
``vendor/miniwob``; nothing listens on a port, so parallel runs cannot collide and a test can
never reach the network by accident. Anything outside that origin is aborted.
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import BrowserContext, Route

ORIGIN = "http://miniwob.local"
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
}


def miniwob_dir() -> Path:
    """The vendored copy: ``core/``, ``common/`` and ``miniwob/`` from the pinned commit."""
    return Path(__file__).resolve().parents[2] / "vendor" / "miniwob"


def task_url(task: str) -> str:
    return f"{ORIGIN}/miniwob/{task}.html"


def task_path(task: str, root: Path | None = None) -> Path:
    return (root or miniwob_dir()) / "miniwob" / f"{task}.html"


def install_routes(context: BrowserContext, root: Path | None = None) -> None:
    """Fulfil ``ORIGIN`` from disk and abort every other request."""
    base = (root or miniwob_dir()).resolve()

    def serve(route: Route) -> None:
        rel = route.request.url[len(ORIGIN) + 1 :].split("?", 1)[0].split("#", 1)[0]
        path = (base / rel).resolve()
        if path.is_relative_to(base) and path.is_file():
            # The pages declare no charset; served without one, Chromium falls back to
            # windows-1252 and unicode-test's "ÖK" arrives as "Ã–K".
            kind = CONTENT_TYPES.get(path.suffix.lower())
            if kind is None:
                route.fulfill(path=str(path))
            else:
                route.fulfill(body=path.read_bytes(), content_type=kind)
        else:
            route.fulfill(status=404, body=f"not vendored: {rel}")

    context.route(f"{ORIGIN}/**", serve)
    context.route(lambda url: not url.startswith(ORIGIN), lambda route: route.abort())
