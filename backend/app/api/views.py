"""Builds the editor's view model from stored flows. Presentation only: no rules here."""

from app.api.schemas import CampaignRef, EditorView, FlowView, RowView
from app.config import Settings
from app.db.repository import StoredFlow
from app.domain.flow import OfferRow, diff, replay
from app.keitaro.schemas import KtOffer
from app.services.flows import Outcome


class Catalog:
    """What the key can read about offers: names and preview links."""

    def __init__(self, offers: list[KtOffer], tracker_host: str):
        self._by_id = {o.id: o for o in offers}
        self._host = tracker_host

    def name(self, offer_id: int) -> str | None:
        offer = self._by_id.get(offer_id)
        return offer.name if offer else None

    def preview_url(self, offer_id: int) -> str | None:
        offer = self._by_id.get(offer_id)
        return f"{self._host}{offer.preview_path}" if offer and offer.preview_path else None


def _change(base: OfferRow | None, row: OfferRow) -> str | None:
    if base is None:
        return "added"
    if base.active != row.active:
        return "removed" if base.active else "restored"
    if row.active and base.share != row.share:
        return "share"
    if row.active and (base.pin is None) != (row.pin is None):
        return "pin"
    return None


def _row(row: OfferRow, base: OfferRow | None, catalog: Catalog) -> RowView:
    return RowView(
        offer_id=row.offer_id, name=catalog.name(row.offer_id), share=row.share,
        pinned=row.active and row.pin is not None, status=row.status.value,
        removed_by=row.removed_by.value if row.removed_by else None, archived=row.archived,
        change=_change(base, row), base_share=base.share if base else None,
        preview_url=catalog.preview_url(row.offer_id),
    )


def flow_view(stored: StoredFlow, catalog: Catalog) -> FlowView:
    working, _ = replay(stored.base, stored.pending)
    changes = diff(stored.base, working)
    return FlowView(
        stream_id=stored.stream_id, name=stored.name, type=stored.type,
        position=stored.position, summary=stored.summary, has_offers=bool(working.rows),
        version=stored.version, dirty=changes.dirty, pending_count=changes.changed,
        total=sum(r.share for r in working.rows if r.active),
        rows=[_row(r, stored.base.find(r.offer_id), catalog) for r in working.rows],
    )


def editor_view(outcome: Outcome, catalog: Catalog, settings: Settings) -> EditorView:
    campaign = outcome.campaign
    fetched = max((f.fetched_at for f in outcome.flows), default=None)
    return EditorView(
        campaign=CampaignRef(id=campaign.id, name=campaign.name),
        kt_url=settings.campaign_admin_url(campaign.id), fetched_at=fetched,
        flows=[flow_view(f, catalog) for f in outcome.flows], notes=outcome.notes,
    )
