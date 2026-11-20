"""FastAPI dependencies. Tests override get_keitaro / get_session / get_settings."""

import time
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import SessionLocal
from app.keitaro.client import KeitaroClient

__all__ = ["get_keitaro", "get_session", "get_settings", "offers_cache"]


async def get_keitaro() -> AsyncIterator[KeitaroClient]:
    settings = get_settings()
    client = KeitaroClient(settings.keitaro_base_url, settings.keitaro_api_key.get_secret_value())
    try:
        yield client
    finally:
        await client.aclose()


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


class TtlCache:
    """One cached value with a time-to-live (the offer list changes rarely)."""

    def __init__(self, ttl_seconds: float, clock: Callable[[], float] = time.monotonic):
        self._ttl = ttl_seconds
        self._clock = clock
        self._value: Any = None
        self._at: float | None = None

    def get(self) -> Any:
        if self._at is None or self._clock() - self._at > self._ttl:
            return None
        return self._value

    def put(self, value: Any) -> None:
        self._value, self._at = value, self._clock()

    def clear(self) -> None:
        self._at = None


offers_cache = TtlCache(60)
