"""AirAware server: `uvicorn airaware.server.app:app`.

Serves the JSON API under /api (interactive docs at /api/docs) and the React frontend built into frontend/dist.
"""

import logging
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from airaware.server import account, admin, db, public
from airaware.server.auth import via_https
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
    if via_https(request):  # browsers then refuse plain-HTTP connections to this site for a year
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    else:
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data: https://tile.openstreetmap.org https://*.tile.openstreetmap.org; style-src 'self' 'unsafe-inline' "
            "https://fonts.googleapis.com; font-src https://fonts.gstatic.com; script-src 'self'; connect-src 'self'; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
    return response


MAX_BODY = 64 * 1024  # every legitimate request is a few hundred bytes of JSON


class BodyLimit:
    """Refuses request bodies over MAX_BODY with 413, by Content-Length up front and by counting streamed bytes,
    so a client cannot make the server buffer megabytes."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        length = dict(scope["headers"]).get(b"content-length")
        if length is not None and (not length.isdigit() or int(length) > MAX_BODY):
            return await JSONResponse({"detail": "Request too large."}, status_code=413)(scope, receive, send)
        seen = 0

        async def limited_receive():
            nonlocal seen
            message = await receive()
            seen += len(message.get("body", b""))
            if seen > MAX_BODY:
                raise TooLarge
            return message
        try:
            await self.app(scope, limited_receive, send)
        except TooLarge:
            await JSONResponse({"detail": "Request too large."}, status_code=413)(scope, receive, send)


class TooLarge(Exception):
    pass


app.add_middleware(BodyLimit)


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, exc: RequestValidationError):
    """422 that says which field is wrong and why, without echoing the input back: FastAPI's default repeats
    the submitted value, which can be a password, and crashes on values JSON cannot hold (NaN)."""
    fields = [{"field": ".".join(str(p) for p in e.get("loc", ())[1:]) or "request", "msg": e.get("msg", "invalid")} for e in exc.errors()]
    return JSONResponse({"detail": "; ".join(f"{f['field']}: {f['msg']}" for f in fields), "errors": fields}, status_code=422)
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
