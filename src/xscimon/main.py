from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .api import api_router
from .config import get_config
from .database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="xscimon", lifespan=lifespan)

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@app.middleware("http")
async def reject_cross_origin_writes(request: Request, call_next):
    """The app has no auth, so any web page open in the browser could POST to
    localhost and trigger paid X/Anthropic calls (CSRF). Browsers always send
    Origin (or at least Referer) on cross-site POSTs, so reject state-changing
    requests whose origin isn't this server. Requests carrying neither header
    (curl, scripts, tests) are allowed."""
    if request.method in _UNSAFE_METHODS:
        source = request.headers.get("origin") or request.headers.get("referer")
        if source and urlsplit(source).netloc != request.headers.get("host"):
            return PlainTextResponse("Cross-origin request rejected", status_code=403)
    return await call_next(request)


def _allowed_hosts() -> list[str]:
    """Block DNS-rebinding: a hostile domain resolved to 127.0.0.1 would pass the
    origin check above, but its Host header won't be one of ours."""
    host = get_config()["server"]["host"]
    if host in ("0.0.0.0", "::"):
        return ["*"]  # deliberately exposed; the operator owns host filtering
    return sorted({host, "127.0.0.1", "localhost", "testserver"})


# Added after the origin check so it wraps it and runs first.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=_allowed_hosts())
app.include_router(api_router)

from .api.views import router as views_router  # noqa: E402
app.include_router(views_router)

STATIC_DIR = Path(__file__).parent / "frontend" / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/health")
def health():
    return {"status": "ok"}
