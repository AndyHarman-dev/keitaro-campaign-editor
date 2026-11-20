from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import FileResponse

from app.api import campaigns, errors, flows, guard
from app.api.deps import Config, Keitaro
from app.api.fake_controls import fake_controls
from app.config import REPO_ROOT, Settings
from app.config import get_settings as load_settings
from app.db.session import session_factory
from app.keitaro.client import KeitaroClient, KeitaroError
from app.keitaro.seed import fake_tracker, with_fake_defaults

FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"

system = APIRouter(prefix="/api")


@system.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@system.get("/keitaro/ping")
async def keitaro_ping(settings: Config, kt: Keitaro) -> dict:
    """Checks that the tracker URL and API key in .env work (lists campaign count)."""
    if not settings.keitaro_configured:
        return {"configured": False}
    try:
        found = await kt.list_campaigns()
    except KeitaroError as exc:
        return {"configured": True, "reachable": False, "status_code": exc.status,
                "campaigns": None}
    return {"configured": True, "reachable": True, "status_code": 200, "campaigns": len(found)}


def _keitaro_factory(app: FastAPI, settings: Settings) -> Callable[[], KeitaroClient]:
    if settings.keitaro_fake:
        fake = fake_tracker(settings)
        app.include_router(fake_controls(fake))
        return lambda: KeitaroClient("https://fake.invalid", "fake", transport=fake.transport)
    key = settings.keitaro_api_key.get_secret_value()
    return lambda: KeitaroClient(settings.keitaro_base_url, key)


def _serve_frontend(app: FastAPI, dist: Path) -> None:
    """Serves the built SPA: real files as they are, any other non-API path as index.html."""
    root = dist.resolve()
    if not (root / "index.html").is_file():
        return

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(status_code=404)
        target = (root / path).resolve()
        if not (path and target.is_file() and target.is_relative_to(root)):
            target = root / "index.html"
        if target.name == "index.html":
            # Always revalidated, so a rebuild reaches open tabs; hashed assets stay cacheable.
            return FileResponse(target, headers={"Cache-Control": "no-cache"})
        return FileResponse(target)


def create_app(settings: Settings, frontend_dist: Path = FRONTEND_DIST) -> FastAPI:
    app = FastAPI(title="Keitaro Campaign Editor")
    if settings.keitaro_fake:
        settings = with_fake_defaults(settings)
    app.state.settings = settings
    app.state.sessions = session_factory(settings.database_url)
    app.state.keitaro_factory = _keitaro_factory(app, settings)
    app.include_router(system)
    app.include_router(campaigns.router)
    app.include_router(flows.router)
    errors.install(app)
    guard.install(app, settings.allowed_hosts)
    _serve_frontend(app, frontend_dist)
    return app


app = create_app(load_settings())
