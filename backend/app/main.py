from fastapi import FastAPI

from app.api import campaigns, errors
from app.config import get_settings
from app.keitaro.client import KeitaroClient, KeitaroError

app = FastAPI(title="Keitaro Campaign Editor")
app.include_router(campaigns.router)
errors.install(app)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/api/keitaro/ping")
async def keitaro_ping() -> dict:
    """Checks that the tracker URL and API key in .env work (lists campaign count)."""
    settings = get_settings()
    if not settings.keitaro_base_url or not settings.keitaro_api_key.get_secret_value():
        return {"configured": False}
    client = KeitaroClient(settings.keitaro_base_url, settings.keitaro_api_key.get_secret_value())
    try:
        campaigns = await client.list_campaigns()
    except KeitaroError as exc:
        return {"configured": True, "reachable": False, "status_code": exc.status,
                "campaigns": None}
    finally:
        await client.aclose()
    return {"configured": True, "reachable": True, "status_code": 200,
            "campaigns": len(campaigns)}
