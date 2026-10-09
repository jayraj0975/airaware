"""AirAware server: `uvicorn airaware.server.app:app`.

Serves the JSON API under /api (interactive docs at /api/docs) and the React frontend built into frontend/dist.
"""

import logging
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from airaware.server import account, admin, db, public
from airaware.server.core import State, refresher, run_job

DIST = Path(os.environ.get("AIRAWARE_FRONTEND", Path(__file__).resolve().parents[2] / "frontend" / "dist"))
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()

    def start():
        app.state.core = State()
        return "data loaded, models trained"

    if not run_job("startup", start):
        raise RuntimeError("Could not load the data or train the models; the error is in the jobs table and the log.")
    if os.environ.get("AIRAWARE_REFRESH", "1") == "1":
        threading.Thread(target=refresher, args=(app.state.core,), daemon=True).start()
    yield


app = FastAPI(title="AirAware API", version="2.0", lifespan=lifespan, docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")


@app.middleware("http")
async def guard(request: Request, call_next):
    """Blocks cross-site writes and adds security headers.

    Every state-changing API call must send `X-AirAware: 1`. A form or script on another site cannot add that header
    without a CORS preflight, and this server never answers preflights, so session cookies cannot be ridden.
    """
    if request.method in UNSAFE and request.url.path.startswith("/api/") and request.headers.get("x-airaware") != "1":
        return JSONResponse({"detail": "Missing X-AirAware header."}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(self), camera=(), microphone=()"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    else:
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data: https://tile.openstreetmap.org https://*.tile.openstreetmap.org; style-src 'self' 'unsafe-inline' "
            "https://fonts.googleapis.com; font-src https://fonts.gstatic.com; script-src 'self'; connect-src 'self'; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
    return response


app.include_router(public.router)
app.include_router(account.router)
app.include_router(admin.router)


@app.get("/api/health")
def health():
    return {"ok": True}


if (DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


@app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
def spa(path: str):
    """Static files from the build, and index.html for every app route (the React router takes it from there)."""
    if path.startswith("api/"):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    f = (DIST / path).resolve()
    if path and f.is_file() and DIST.resolve() in f.parents:
        return FileResponse(f)
    index = DIST / "index.html"
    if not index.exists():
        return JSONResponse({"detail": "Frontend not built. Run: cd frontend && npm install && npm run build"}, status_code=503)
    return FileResponse(index)
