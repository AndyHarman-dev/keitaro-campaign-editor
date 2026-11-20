"""Pure domain core: offer rows, share allocation and staged operations.

No I/O here. Every function returns new values; notes for the user are returned, never
printed. Rules: vision §2 "Share & pin rules" and §5.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum


class RowStatus(StrEnum):
    ACTIVE = "active"
    REMOVED = "removed"


class RemovedBy(StrEnum):
    LOCAL = "local"
    KEITARO = "keitaro"


def _check_percent(value: int) -> None:
    if not 0 <= value <= 100:
        raise ValueError(f"share must be 0..100, got {value}")


@dataclass(frozen=True)
class Pin:
    share: int
    seq: int  # age: lower = older; auto-unpin releases the lowest first

    def __post_init__(self) -> None:
        _check_percent(self.share)


@dataclass(frozen=True)
class OfferRow:
    offer_id: int
    status: RowStatus
    share: int
    kt_state: str = "active"
    pin: Pin | None = None  # dormant while the row is removed
    removed_by: RemovedBy | None = None
    archived: bool = False

    def __post_init__(self) -> None:
        _check_percent(self.share)
        if self.status is RowStatus.ACTIVE:
            self._check_active()
        else:
            self._check_removed()

    def _check_active(self) -> None:
        if self.removed_by is not None or self.archived:
            raise ValueError("an active row cannot be removed or archived")
        if self.pin is not None and self.pin.share != self.share:
            raise ValueError("an active pinned row shows its pinned share")

    def _check_removed(self) -> None:
        if self.share != 0:
            raise ValueError("a removed row has share 0")
        if self.removed_by is None:
            raise ValueError("a removed row says who removed it")

    @property
    def active(self) -> bool:
        return self.status is RowStatus.ACTIVE


@dataclass(frozen=True)
class FlowState:
    rows: tuple[OfferRow, ...]
    next_pin_seq: int = 1

    def __post_init__(self) -> None:
        ids = [r.offer_id for r in self.rows]
        if len(ids) != len(set(ids)):
            raise ValueError("offer ids must be unique in a flow")

    def find(self, offer_id: int) -> OfferRow | None:
        return next((r for r in self.rows if r.offer_id == offer_id), None)

    def put(self, row: OfferRow) -> FlowState:
        rows = tuple(row if r.offer_id == row.offer_id else r for r in self.rows)
        return replace(self, rows=rows)


# --- operations --------------------------------------------------------------------------


@dataclass(frozen=True)
class Remove:
    offer_id: int


@dataclass(frozen=True)
class BringBack:
    offer_id: int


@dataclass(frozen=True)
class Add:
    offer_id: int


@dataclass(frozen=True)
class SetShare:
    offer_id: int
    share: int

    def __post_init__(self) -> None:
        _check_percent(self.share)


@dataclass(frozen=True)
class TogglePin:
    offer_id: int


Op = Remove | BringBack | Add | SetShare | TogglePin
Result = tuple[FlowState, list[str]]


def _not_in_flow(state: FlowState, offer_id: int) -> Result:
    return state, [f"Offer [{offer_id}] is not in this flow."]


def _archived(state: FlowState, offer_id: int) -> Result:
    return state, [f"Offer [{offer_id}] is archived in Keitaro and can't be restored."]


def _remove(state: FlowState, op: Remove) -> Result:
    row = state.find(op.offer_id)
    if row is None:
        return _not_in_flow(state, op.offer_id)
    if not row.active:
        return state, [f"Offer [{op.offer_id}] is already removed."]
    removed = replace(row, status=RowStatus.REMOVED, share=0, removed_by=RemovedBy.LOCAL)
    return state.put(removed), []


def _bring_back(state: FlowState, op: BringBack) -> Result:
    row = state.find(op.offer_id)
    if row is None:
        return _not_in_flow(state, op.offer_id)
    if row.archived:
        return _archived(state, op.offer_id)
    if row.active:
        return state, [f"Offer [{op.offer_id}] is already in this flow."]
    share = row.pin.share if row.pin else 0
    back = replace(row, status=RowStatus.ACTIVE, share=share, removed_by=None)
    notes = [f"Brought back [{op.offer_id}] with its pin at {share}%."] if row.pin else []
    return state.put(back), notes


def _add(state: FlowState, op: Add) -> Result:
    row = state.find(op.offer_id)
    if row is None:
        new = OfferRow(offer_id=op.offer_id, status=RowStatus.ACTIVE, share=0)
        return replace(state, rows=(*state.rows, new)), []
    return _bring_back(state, BringBack(op.offer_id))


def _editable(state: FlowState, offer_id: int) -> OfferRow | Result:
    row = state.find(offer_id)
    if row is None:
        return _not_in_flow(state, offer_id)
    if not row.active:
        return state, [f"Offer [{offer_id}] is removed; bring it back first."]
    return row


def _pin(state: FlowState, row: OfferRow, share: int) -> FlowState:
    pinned = replace(row, share=share, pin=Pin(share=share, seq=state.next_pin_seq))
    return replace(state.put(pinned), next_pin_seq=state.next_pin_seq + 1)


def _set_share(state: FlowState, op: SetShare) -> Result:
    row = _editable(state, op.offer_id)
    if not isinstance(row, OfferRow):
        return row
    return _pin(state, row, op.share), []


def _toggle_pin(state: FlowState, op: TogglePin) -> Result:
    row = _editable(state, op.offer_id)
    if not isinstance(row, OfferRow):
        return row
    if row.pin is not None:
        return state.put(replace(row, pin=None)), []
    return _pin(state, row, row.share), []


_HANDLERS = {
    Remove: _remove,
    BringBack: _bring_back,
    Add: _add,
    SetShare: _set_share,
    TogglePin: _toggle_pin,
}


def apply(state: FlowState, op: Op) -> Result:
    """Applies one staged operation. Total: an op that no longer applies is a no-op + note."""
    after, notes = _HANDLERS[type(op)](state, op)
    if after == state:
        return state, notes
    balanced, unpin_notes = rebalance(after)
    return balanced, notes + unpin_notes


def replay(base: FlowState, ops: list[Op]) -> Result:
    state, notes = base, []
    for op in ops:
        state, op_notes = apply(state, op)
        notes += op_notes
    return state, notes


def effective(base: FlowState, ops: list[Op]) -> list[Op]:
    """The ops that still change something when replayed on `base`, in order."""
    kept, state = [], base
    for op in ops:
        after, _ = apply(state, op)
        if after != state:
            kept.append(op)
        state = after
    return kept


# --- allocation --------------------------------------------------------------------------


def _pins_fit(active: list[OfferRow]) -> bool:
    pinned_total = sum(r.share for r in active if r.pin is not None)
    has_free = any(r.pin is None for r in active)
    return pinned_total <= 100 and (has_free or pinned_total == 100)


def _release_oldest_pin(state: FlowState) -> tuple[FlowState, str]:
    oldest = min((r for r in state.rows if r.active and r.pin), key=lambda r: r.pin.seq)
    note = f"Auto-unpinned [{oldest.offer_id}]: the pinned shares did not fit in 100%."
    return state.put(replace(oldest, pin=None)), note


def _split_free(state: FlowState) -> FlowState:
    active = [r for r in state.rows if r.active]
    free = [r for r in active if r.pin is None]
    if not free:
        return state
    rest = 100 - sum(r.share for r in active if r.pin is not None)
    each, remainder = divmod(rest, len(free))
    for i, row in enumerate(free):
        state = state.put(replace(row, share=each + (1 if i < remainder else 0)))
    return state


def rebalance(state: FlowState) -> Result:
    """Unpinned active rows split what the pins leave; pins that cannot fit are released."""
    notes = []
    while (active := [r for r in state.rows if r.active]) and not _pins_fit(active):
        state, note = _release_oldest_pin(state)
        notes.append(note)
    return _split_free(state), notes


# --- forget, diff, push ------------------------------------------------------------------


class NotArchived(ValueError):
    pass


def forget(state: FlowState, offer_id: int) -> FlowState:
    """Drops an archived row for good (a local base edit, nothing is sent to Keitaro)."""
    row = state.find(offer_id)
    if row is None or not row.archived:
        raise NotArchived(f"offer [{offer_id}] is not an archived row")
    return replace(state, rows=tuple(r for r in state.rows if r.offer_id != offer_id))


@dataclass(frozen=True)
class FlowDiff:
    changed: int

    @property
    def dirty(self) -> bool:
        return self.changed > 0


def diff(base: FlowState, working: FlowState) -> FlowDiff:
    before = {r.offer_id: r for r in base.rows}
    # Ops never drop rows (only forget() does, and it edits the base), so comparing the
    # working rows against the base covers every change.
    changed = sum(1 for r in working.rows if before.get(r.offer_id) != r)
    return FlowDiff(changed=changed)


class InvalidPush(ValueError):
    pass


@dataclass(frozen=True)
class OfferLink:
    """One entry of Keitaro's `offers` list on PUT /streams/{id}."""

    offer_id: int
    share: int
    state: str


def push_plan(working: FlowState) -> list[OfferLink]:
    """The complete offer list to send. Keitaro replaces the whole list and does not
    validate shares, so the total is checked here."""
    links = [OfferLink(r.offer_id, r.share, r.kt_state) for r in working.rows if r.active]
    total = sum(link.share for link in links)
    if not links or total != 100:
        raise InvalidPush(f"active shares must total 100 (got {total} over {len(links)})")
    return links


# --- fetch merge ---------------------------------------------------------------------------


def signature(kt_offers: list[OfferLink]) -> list[list[int | str]]:
    """What Keitaro had, in order; compared before a push to detect changes made in Keitaro."""
    return [[link.offer_id, link.share, link.state] for link in kt_offers]


def _from_keitaro(link: OfferLink, old: OfferRow | None) -> OfferRow:
    pin = Pin(share=link.share, seq=old.pin.seq) if old and old.pin else None
    return OfferRow(offer_id=link.offer_id, status=RowStatus.ACTIVE, share=link.share,
                    kt_state=link.state, pin=pin)


def _gone_from_keitaro(old: OfferRow, archived_ids: set[int]) -> tuple[OfferRow, list[str]]:
    notes = []
    row = old
    if old.active:
        row = replace(old, status=RowStatus.REMOVED, share=0, removed_by=RemovedBy.KEITARO)
        notes.append(f"Offer [{old.offer_id}] was removed from this flow in Keitaro. "
                     "Bring back + Push re-attaches it.")
    if old.offer_id in archived_ids and not old.archived:
        row = replace(row, archived=True)
        notes.append(f"Offer [{old.offer_id}] was archived in Keitaro and can't be restored.")
    return row, notes


def merge_fetch(old_base: FlowState, kt_offers: list[OfferLink],
                archived_ids: set[int]) -> Result:
    """New base: Keitaro's rows in Keitaro's order, plus every remembered row Keitaro no longer
    has, kept as removed right after the row it used to follow. Pins are local and survive."""
    rows = [_from_keitaro(link, old_base.find(link.offer_id)) for link in kt_offers]
    in_keitaro = {link.offer_id for link in kt_offers}
    notes: list[str] = []
    previous: int | None = None
    for old in old_base.rows:
        if old.offer_id not in in_keitaro:
            row, row_notes = _gone_from_keitaro(old, archived_ids)
            at = 0 if previous is None else _index(rows, previous) + 1
            rows.insert(at, row)
            notes += row_notes
        previous = old.offer_id
    return FlowState(rows=tuple(rows), next_pin_seq=old_base.next_pin_seq), notes


def _index(rows: list[OfferRow], offer_id: int) -> int:
    return next(i for i, r in enumerate(rows) if r.offer_id == offer_id)
