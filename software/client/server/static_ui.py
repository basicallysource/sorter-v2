"""Serve the built SvelteKit SPA from the FastAPI Station server.

The UI is built (``npm run build`` in ``software/ui``) into ``ui/build`` as a static
single-page app with a ``200.html`` fallback. Mounting it here lets the AGX serve the
whole client from one origin (``http://<host>.local:8000``) with no Node at runtime —
the laptop only needs a browser.

Call ``mount_ui(app)`` AFTER every API/websocket route is registered: the catch-all
fallback below matches any unmatched GET, so anything registered after it would be
shadowed.
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

UI_BUILD_DIR = Path(__file__).resolve().parent.parent.parent / "ui" / "build"


def mount_ui(app: FastAPI) -> None:
    """Mount the built SPA, or no-op (API-only) if it hasn't been built yet."""
    if not UI_BUILD_DIR.is_dir():
        return

    app_assets = UI_BUILD_DIR / "_app"
    if app_assets.is_dir():
        # Hashed, immutable build assets.
        app.mount("/_app", StaticFiles(directory=app_assets), name="ui_app")

    fallback = UI_BUILD_DIR / "200.html"

    @app.get("/{path:path}")
    def spa(path: str) -> FileResponse:
        # Serve a real static file when one exists (favicon, robots.txt, etc.),
        # otherwise hand back the SPA shell for client-side routing.
        candidate = (UI_BUILD_DIR / path).resolve()
        if UI_BUILD_DIR in candidate.parents and candidate.is_file():
            return FileResponse(candidate)
        if fallback.is_file():
            return FileResponse(fallback)
        raise HTTPException(status_code=404, detail="UI not built")
