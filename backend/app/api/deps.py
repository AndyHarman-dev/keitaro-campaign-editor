"""FastAPI dependencies. create_app() puts what they hand out on app.state; tests may override."""

import time
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.config import Settings
from app.keitaro.client import KeitaroClient
from app.keitaro.schemas import KtOffer

__all__ = ["Config", "Db", "Keitaro", "cached_offers", "get_keitaro", "get_session", "get_settings",
           "offers_cache"]


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


async def get_keitaro(request: Request) -> AsyncIterator[KeitaroClient]:
    client = request.app.state.keitaro_factory()
    try:
        yield client
    finally:
        await client.aclose()


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.sessions() as session:
        yield session


Keitaro = Annotated[KeitaroClient, Depends(get_keitaro)]
Db = Annotated[Session, Depends(get_session)]
Config = Annotated[Settings, Depends(get_settings)]


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


async def cached_offers(kt: KeitaroClient) -> list[KtOffer]:
    """The offers this key can read, cached for a minute (search, Show all offers, names)."""
    offers = offers_cache.get()
    if offers is None:
        offers = await kt.list_offers()
        offers_cache.put(offers)
    return offers
