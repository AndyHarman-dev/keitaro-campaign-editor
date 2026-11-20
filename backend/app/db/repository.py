"""Storage of flows and created campaigns. The ORM stays behind this module."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.codec import ops_from_json, ops_to_json, state_from_json, state_to_json
from app.db.models import CreatedCampaign, FlowRecord
from app.domain.flow import FlowState, Op


class StaleVersion(Exception):
    """The flow changed since the caller read it (another tab, or a concurrent request)."""


@dataclass(frozen=True)
class StoredFlow:
    stream_id: int
    campaign_id: int
    name: str
    type: str
    position: int
    summary: str
    base: FlowState
    pending: list[Op]
    signature: list[Any]
    fetched_at: datetime
    version: int  # 0 = not stored yet


def _to_stored(rec: FlowRecord) -> StoredFlow:
    fetched = rec.fetched_at if rec.fetched_at.tzinfo else rec.fetched_at.replace(tzinfo=UTC)
    return StoredFlow(stream_id=rec.stream_id, campaign_id=rec.campaign_id, name=rec.name,
                      type=rec.type, position=rec.position, summary=rec.summary,
                      base=state_from_json(rec.base), pending=ops_from_json(rec.pending),
                      signature=rec.kt_signature, fetched_at=fetched, version=rec.version)


def _columns(flow: StoredFlow) -> dict[str, Any]:
    return {"campaign_id": flow.campaign_id, "name": flow.name, "type": flow.type,
                "position": flow.position, "summary": flow.summary, "base": state_to_json(flow.base),
                "pending": ops_to_json(flow.pending), "kt_signature": flow.signature,
                "fetched_at": flow.fetched_at}


class FlowRepository:
    def __init__(self, session: Session):
        self._s = session

    def get(self, stream_id: int) -> StoredFlow | None:
        rec = self._s.get(FlowRecord, stream_id)
        return _to_stored(rec) if rec else None

    def for_campaign(self, campaign_id: int) -> list[StoredFlow]:
        query = select(FlowRecord).where(FlowRecord.campaign_id == campaign_id)
        return [_to_stored(r) for r in self._s.scalars(query.order_by(FlowRecord.position))]

    def delete(self, stream_id: int) -> None:
        self._s.query(FlowRecord).filter_by(stream_id=stream_id).delete()

    def save(self, flow: StoredFlow) -> StoredFlow:
        """Writes `flow` if the stored version is still `flow.version`; returns it bumped."""
        if flow.version == 0:
            self._insert(flow)
        else:
            self._update(flow)
        self._s.expire_all()
        return replace(flow, version=flow.version + 1)

    def _insert(self, flow: StoredFlow) -> None:
        if self._s.get(FlowRecord, flow.stream_id) is not None:
            raise StaleVersion(f"flow {flow.stream_id} already exists")
        self._s.add(FlowRecord(stream_id=flow.stream_id, version=1, **_columns(flow)))
        self._s.flush()

    def _update(self, flow: StoredFlow) -> None:
        result = self._s.execute(
            update(FlowRecord)
            .where(FlowRecord.stream_id == flow.stream_id, FlowRecord.version == flow.version)
            .values(version=flow.version + 1, **_columns(flow))
        )
        if result.rowcount != 1:
            raise StaleVersion(f"flow {flow.stream_id} changed since version {flow.version}")


class CampaignLog:
    def __init__(self, session: Session):
        self._s = session

    def find(self, idempotency_key: str) -> int | None:
        rec = self._s.get(CreatedCampaign, idempotency_key)
        return rec.campaign_id if rec else None

    def record(self, idempotency_key: str, campaign_id: int) -> None:
        self._s.add(CreatedCampaign(idempotency_key=idempotency_key, campaign_id=campaign_id,
                                    created_at=datetime.now(UTC)))
        self._s.flush()
