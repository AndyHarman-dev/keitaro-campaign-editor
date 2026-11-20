"""Test-only controls that simulate someone editing Keitaro directly, and fake traffic for the
stats beta. Mounted only when KEITARO_FAKE=1, never against a real tracker."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

from app.api.deps import KeyedTtlCache, offers_cache
from app.keitaro.fake import FakeKeitaro
from app.keitaro.traffic import OfferProfile, simulate


class TrafficIn(BaseModel):
    campaign_id: int
    days: int = Field(default=30, ge=0, le=366)
    clicks_per_day: int = Field(default=1000, ge=0, le=1_000_000)
    seed: int = 1
    lag: bool = True
    drift: dict[int, float] = {}
    no_offer: float = 0.0


class ProfileIn(BaseModel):
    cr_all: float
    approve: float
    payout: Decimal


class FailNextIn(BaseModel):
    status: int = 503
    message: str = "Service unavailable"


def fake_controls(fake: FakeKeitaro, stats_cache: KeyedTtlCache,
                  today: Callable[[], date]) -> APIRouter:
    router = APIRouter(prefix="/api/_fake", include_in_schema=False)

    def done() -> Response:
        stats_cache.clear()  # a warm cache must never hide what a control just changed
        return Response(status_code=204)

    @router.post("/streams/{stream_id}/detach/{offer_id}", status_code=204)
    def detach(stream_id: int, offer_id: int) -> Response:
        fake.detach_offer(stream_id, offer_id)
        return Response(status_code=204)

    @router.post("/offers/{offer_id}/archive", status_code=204)
    def archive(offer_id: int) -> Response:
        fake.archive_offer(offer_id)
        offers_cache.clear()
        return Response(status_code=204)

    @router.post("/traffic", status_code=204)
    def traffic(body: TrafficIn) -> Response:
        simulate(fake, body.campaign_id, body.days, body.clicks_per_day, today=today(),
                 seed=body.seed, lag=body.lag, drift=body.drift, no_offer=body.no_offer)
        fake.save()
        return done()

    @router.delete("/traffic", status_code=204)
    def clear_traffic(campaign_id: int) -> Response:
        fake.traffic = {key: c for key, c in fake.traffic.items() if key[0] != campaign_id}
        fake.save()
        return done()

    @router.put("/offers/{offer_id}/profile", status_code=204)
    def profile(offer_id: int, body: ProfileIn) -> Response:
        fake.profiles[offer_id] = OfferProfile(body.cr_all, body.approve, body.payout)
        return done()

    @router.post("/fail-next", status_code=204)
    def fail_next(body: FailNextIn) -> Response:
        fake.fail_next("POST", "/report/build", body.status, body.message)
        return done()

    return router
