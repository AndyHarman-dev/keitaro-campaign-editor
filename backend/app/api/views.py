"""Builds the editor's view model from stored flows. Presentation only: no rules here."""

from app.api.schemas import CampaignRef, EditorView, FlowView, RowView
from app.config import Settings
from app.db.repository import StoredFlow
from app.domain.flow import OfferRow, diff, replay
from app.services.flows import Outcome


def _change(base: OfferRow | None, row: OfferRow) -> str | None:
    if base is None:
        return "added"
    if base.active != row.active:
        return "removed" if base.active else "restored"
    if row.active and base.share != row.share:
        return "share"
    return None


def _row(row: OfferRow, base: OfferRow | None, names: dict[int, str]) -> RowView:
    return RowView(
        offer_id=row.offer_id, name=names.get(row.offer_id), share=row.share,
        pinned=row.active and row.pin is not None, status=row.status.value,
        removed_by=row.removed_by.value if row.removed_by else None, archived=row.archived,
        change=_change(base, row), base_share=base.share if base else None,
    )


def flow_view(stored: StoredFlow, names: dict[int, str]) -> FlowView:
    working, _ = replay(stored.base, stored.pending)
    changes = diff(stored.base, working)
    return FlowView(
        stream_id=stored.stream_id, name=stored.name, type=stored.type,
        position=stored.position, summary=stored.summary, has_offers=bool(working.rows),
        version=stored.version, dirty=changes.dirty, pending_count=changes.changed,
        rows=[_row(r, stored.base.find(r.offer_id), names) for r in working.rows],
    )


def editor_view(outcome: Outcome, names: dict[int, str], settings: Settings) -> EditorView:
    campaign = outcome.campaign
    fetched = max((f.fetched_at for f in outcome.flows), default=None)
    return EditorView(
        campaign=CampaignRef(id=campaign.id, name=campaign.name),
        kt_url=settings.campaign_admin_url(campaign.id), fetched_at=fetched,
        flows=[flow_view(f, names) for f in outcome.flows], notes=outcome.notes,
    )
