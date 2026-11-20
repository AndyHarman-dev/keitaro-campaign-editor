"""FastAPI dependencies. create_app() puts what they hand out on app.state; tests may override."""

import time
from collections.abc import AsyncIterator, Callable, Hashable, Iterator
from datetime import date
from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.config import Settings
from app.keitaro.client import KeitaroClient
from app.keitaro.schemas import KtOffer

__all__ = ["Config", "Db", "Keitaro", "KeyedTtlCache", "StatsCache", "Today", "cached_offers",
           "get_keitaro", "get_session", "get_settings", "get_stats_cache", "get_today",
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


def get_today(request: Request) -> date:
    """Today in the configured stats timezone; tests override it with a fixed date."""
    return request.app.state.today()


def get_stats_cache(request: Request) -> "KeyedTtlCache":
    return request.app.state.stats_cache


Keitaro = Annotated[KeitaroClient, Depends(get_keitaro)]
Db = Annotated[Session, Depends(get_session)]
Config = Annotated[Settings, Depends(get_settings)]
Today = Annotated[date, Depends(get_today)]


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


class KeyedTtlCache:
    """One TtlCache per key, e.g. stats per (campaign, period).

    `stamp()` before a slow read and `put(..., stamp=)` after it: a drop or clear in between
    means the value may predate it, so it isn't stored.
    """

    def __init__(self, ttl_seconds: float, clock: Callable[[], float] = time.monotonic):
        self._ttl = ttl_seconds
        self._clock = clock
        self._items: dict[Hashable, TtlCache] = {}
        self._epoch = object()  # replaced on every drop or clear

    def stamp(self) -> object:
        return self._epoch

    def get(self, key: Hashable) -> Any:
        item = self._items.get(key)
        return None if item is None else item.get()

    def put(self, key: Hashable, value: Any, stamp: object | None = None) -> None:
        if stamp is not None and stamp is not self._epoch:
            return
        self._items = {k: c for k, c in self._items.items() if c.get() is not None}
        self._items.setdefault(key, TtlCache(self._ttl, self._clock)).put(value)

    def drop(self, matches: Callable[[Hashable], bool]) -> None:
        self._items = {k: c for k, c in self._items.items() if not matches(k)}
        self._epoch = object()

    def clear(self) -> None:
        self._items.clear()
        self._epoch = object()


StatsCache = Annotated[KeyedTtlCache, Depends(get_stats_cache)]

offers_cache = TtlCache(60)


async def cached_offers(kt: KeitaroClient) -> list[KtOffer]:
    """The offers this key can read, cached for a minute (search, Show all offers, names)."""
    offers = offers_cache.get()
    if offers is None:
        offers = await kt.list_offers()
        offers_cache.put(offers)
    return offers
