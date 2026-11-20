"""Test-only controls that simulate someone editing Keitaro directly. Mounted only when
KEITARO_FAKE=1, never against a real tracker."""

from fastapi import APIRouter, Response

from app.api.deps import offers_cache
from app.keitaro.fake import FakeKeitaro


def fake_controls(fake: FakeKeitaro) -> APIRouter:
    router = APIRouter(prefix="/api/_fake", include_in_schema=False)

    @router.post("/streams/{stream_id}/detach/{offer_id}", status_code=204)
    def detach(stream_id: int, offer_id: int) -> Response:
        fake.detach_offer(stream_id, offer_id)
        return Response(status_code=204)

    @router.post("/offers/{offer_id}/archive", status_code=204)
    def archive(offer_id: int) -> Response:
        fake.archive_offer(offer_id)
        offers_cache.clear()
        return Response(status_code=204)

    return router
