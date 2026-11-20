"""The editor's use cases: fetch, staged ops, push, cancel (plan Phase 6).

Only this module writes flow rows (single writer, plan decision 14). Every write checks the
version the caller saw. Push re-reads the flow from Keitaro first and refuses when it
changed since our fetch; Keitaro's PUT replaces the whole offer list, so the payload is the
complete working list (plan decisions 6 and 7).
"""

from dataclasses import dataclass, replace
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.repository import FlowRepository, StaleVersion, StoredFlow
from app.domain.flow import (
    FlowState,
    Op,
    diff,
    forget,
    merge_fetch,
    push_plan,
    replay,
    signature,
)
from app.keitaro.client import KeitaroClient
from app.keitaro.schemas import KtCampaign, KtStream

__all__ = ["Conflict", "FlowNotFound", "FlowService", "StaleVersion"]


class FlowNotFound(Exception):
    pass


class Conflict(Exception):
    """The flow changed in Keitaro since our last fetch; Fetch first."""


def summary(stream: KtStream) -> str:
    if stream.schema_ == "redirect":
        where = f"country in {', '.join(stream.countries)} → " if stream.countries else ""
        return f"{stream.type} · {where}{stream.redirect_url or 'redirect'}"
    return f"{stream.type} · position {stream.position}"


@dataclass(frozen=True)
class Outcome:
    """What a use case leaves behind: the campaign's flows, plus notes for the user."""

    campaign: KtCampaign
    flows: list[StoredFlow]
    notes: list[str]


class FlowService:
    def __init__(self, kt: KeitaroClient, session: Session):
        self._kt = kt
        self._s = session
        self._repo = FlowRepository(session)

    # --- reads -----------------------------------------------------------------------

    async def open(self, campaign_id: int) -> Outcome:
        campaign = await self._kt.get_campaign(campaign_id)
        flows = self._repo.for_campaign(campaign_id)
        if not flows:
            return await self.fetch(campaign_id)
        return Outcome(campaign, flows, [])

    def _load(self, stream_id: int, version: int) -> StoredFlow:
        stored = self._repo.get(stream_id)
        if stored is None:
            raise FlowNotFound(f"flow {stream_id} is not in the editor; open its campaign first")
        if stored.version != version:
            raise StaleVersion(f"flow {stream_id} changed since version {version}")
        return stored

    async def outcome(self, campaign_id: int, notes: list[str]) -> Outcome:
        campaign = await self._kt.get_campaign(campaign_id)
        return Outcome(campaign, self._repo.for_campaign(campaign_id), notes)

    async def reload(self, stream_id: int, notes: list[str]) -> Outcome:
        """The campaign around `stream_id`, as stored now."""
        stored = self._repo.get(stream_id)
        if stored is None:
            raise FlowNotFound(f"flow {stream_id} is not in the editor")
        return await self.outcome(stored.campaign_id, notes)

    # --- fetch -----------------------------------------------------------------------

    async def fetch(self, campaign_id: int) -> Outcome:
        campaign = await self._kt.get_campaign(campaign_id)
        streams = await self._kt.list_streams(campaign_id)
        archived = await self._kt.list_deleted_offer_ids()
        notes: list[str] = []
        for stream in streams:
            notes += self._merge(stream, archived)
        self._s.commit()
        return Outcome(campaign, self._repo.for_campaign(campaign_id), notes)

    def _merge(self, stream: KtStream, archived: set[int]) -> list[str]:
        stored = self._repo.get(stream.id)
        old_base = stored.base if stored else FlowState(rows=())
        pending = stored.pending if stored else []
        base, notes = merge_fetch(old_base, stream.links, archived)
        working, replay_notes = replay(base, pending)
        fresh = StoredFlow(
            stream_id=stream.id, campaign_id=stream.campaign_id, name=stream.name,
            type=stream.type, position=stream.position, summary=summary(stream), base=base,
            pending=pending if diff(base, working).dirty else [],
            signature=signature(stream.links), fetched_at=datetime.now(UTC),
            version=stored.version if stored else 0,
        )
        self._repo.save(fresh)
        return [f"{stream.name}: {n}" for n in notes + replay_notes]

    # --- staged edits ----------------------------------------------------------------

    async def apply(self, stream_id: int, version: int, op: Op) -> Outcome:
        stored = self._load(stream_id, version)
        before, _ = replay(stored.base, stored.pending)
        after, notes = replay(before, [op])
        if after != before:
            pending = [*stored.pending, op] if diff(stored.base, after).dirty else []
            self._repo.save(replace(stored, pending=pending))
            self._s.commit()
        return await self.outcome(stored.campaign_id, [f"{stored.name}: {n}" for n in notes])

    async def forget(self, stream_id: int, version: int, offer_id: int) -> Outcome:
        """Drops an archived row for good. Local only: nothing is sent to Keitaro."""
        stored = self._load(stream_id, version)
        self._repo.save(replace(stored, base=forget(stored.base, offer_id)))
        self._s.commit()
        return await self.outcome(stored.campaign_id, [])

    async def cancel(self, versions: dict[int, int]) -> None:
        for stream_id, version in versions.items():
            stored = self._load(stream_id, version)
            if stored.pending:
                self._repo.save(replace(stored, pending=[]))
        self._s.commit()

    # --- push ------------------------------------------------------------------------

    async def push(self, stream_id: int, version: int) -> list[str]:
        stored = self._load(stream_id, version)
        working, _ = replay(stored.base, stored.pending)
        if not diff(stored.base, working).dirty:
            return []
        plan = push_plan(working)
        current = await self._kt.get_stream(stream_id)
        if signature(current.links) != stored.signature:
            raise Conflict(f"{stored.name} was changed in Keitaro since your last fetch.")
        await self._kt.put_stream_offers(stream_id, plan)
        after = await self._kt.get_stream(stream_id)
        base, _ = merge_fetch(working, after.links, set())
        self._repo.save(replace(stored, base=base, pending=[], signature=signature(after.links),
                                fetched_at=datetime.now(UTC)))
        self._s.commit()
        if signature(after.links) != signature(plan):
            # Plan Phase 6 tripwire: Keitaro normalised what we sent. Its version is kept.
            return [(f"{stored.name}: Keitaro stored a different offer list than was sent; "
                    "showing what Keitaro has.")]
        return []

    async def push_all(self, versions: dict[int, int]) -> list[str]:
        """Pushes each flow on its own; a conflict in one does not stop the others."""
        for stream_id, version in versions.items():
            self._load(stream_id, version)
        notes = []
        for stream_id, version in versions.items():
            try:
                notes += await self.push(stream_id, version)
            except Conflict as exc:
                notes.append(str(exc))
        return notes
