from fastapi import FastAPI

from app.config import get_settings
from app.keitaro.client import KeitaroClient

app = FastAPI(title="Keitaro Campaign Editor")


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/api/keitaro/ping")
async def keitaro_ping() -> dict:
    """Checks that the tracker URL and API key in .env work (lists campaign count)."""
    settings = get_settings()
    if not settings.keitaro_base_url or not settings.keitaro_api_key.get_secret_value():
        return {"configured": False}
    client = KeitaroClient(settings)
    try:
        resp = await client.get("/campaigns")
        ok = resp.status_code == 200
        return {
            "configured": True,
            "reachable": ok,
            "status_code": resp.status_code,
            "campaigns": len(resp.json()) if ok else None,
        }
    finally:
        await client.aclose()
