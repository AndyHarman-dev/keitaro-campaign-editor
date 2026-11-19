"""Thin async client for the Keitaro Admin API (v1).

The API key is sent in the `Api-Key` header and must never be logged.
"""

import httpx

from app.config import Settings


class KeitaroClient:
    def __init__(self, settings: Settings):
        self._http = httpx.AsyncClient(
            base_url=settings.keitaro_api_root,
            headers={"Api-Key": settings.keitaro_api_key.get_secret_value()},
            timeout=20.0,
        )

    async def get(self, path: str, **params) -> httpx.Response:
        return await self._http.get(path, params=params or None)

    async def aclose(self) -> None:
        await self._http.aclose()
