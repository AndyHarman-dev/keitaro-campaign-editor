"""Fetch merge: a new base from Keitaro, pending ops replayed on top (plan Phase 2)."""

from hypothesis import given
from hypothesis import strategies as st

from app.domain.flow import (
    Add,
    BringBack,
    FlowState,
    OfferLink,
    OfferRow,
    Pin,
    Remove,
    RemovedBy,
    RowStatus,
    SetShare,
    TogglePin,
    diff,
    merge_fetch,
    replay,
    signature,
)


def active(offer_id: int, share: int, pin: Pin | None = None, state: str = "active") -> OfferRow:
    return OfferRow(offer_id=offer_id, status=RowStatus.ACTIVE, share=share, kt_state=state,
                    pin=pin)


def removed(offer_id: int, by: RemovedBy, pin: Pin | None = None, archived: bool = False,
            state: str = "active") -> OfferRow:
    return OfferRow(offer_id=offer_id, status=RowStatus.REMOVED, share=0, kt_state=state,
                    pin=pin, removed_by=by, archived=archived)


def links(*pairs: tuple[int, int]) -> list[OfferLink]:
    return [OfferLink(offer_id=o, share=s, state="active") for o, s in pairs]


def base(*rows: OfferRow, next_pin_seq: int = 1) -> FlowState:
    return FlowState(rows=rows, next_pin_seq=next_pin_seq)


def test_first_fetch_takes_keitaro_rows_as_they_are():
    new, notes = merge_fetch(base(), links((1, 50), (2, 25), (3, 25)), set())
    assert new == base(active(1, 50), active(2, 25), active(3, 25))
    assert notes == []


def test_offer_added_in_keitaro_appears_at_its_keitaro_position():
    new, _ = merge_fetch(base(active(1, 50), active(3, 50)), links((1, 40), (2, 20), (3, 40)),
                         set())
    assert [r.offer_id for r in new.rows] == [1, 2, 3]
    assert [r.share for r in new.rows] == [40, 20, 40]


def test_offer_gone_from_keitaro_is_kept_as_removed_in_keitaro():
    old = base(active(1, 50), active(2, 50, state="disabled"))
    new, notes = merge_fetch(old, links((1, 100)), set())
    assert new.rows == (active(1, 100), removed(2, RemovedBy.KEITARO, state="disabled"))
    assert notes == [("Offer [2] was removed from this flow in Keitaro. Bring back + Push "
                     "re-attaches it.")]


def test_offer_we_removed_and_pushed_stays_removed_by_us():
    old = base(active(1, 100), removed(2, RemovedBy.LOCAL))
    new, notes = merge_fetch(old, links((1, 100)), set())
    assert new == old
    assert notes == []


def test_removed_offer_that_is_archived_in_keitaro_is_flagged():
    old = base(active(1, 50), active(2, 50))
    new, notes = merge_fetch(old, links((1, 100)), {2})
    assert new.rows[1] == removed(2, RemovedBy.KEITARO, archived=True)
    assert notes[-1] == "Offer [2] was archived in Keitaro and can't be restored."


def test_archived_flag_is_reported_once():
    old = base(active(1, 100), removed(2, RemovedBy.KEITARO, archived=True))
    new, notes = merge_fetch(old, links((1, 100)), {2})
    assert new == old
    assert notes == []


def test_unreadable_but_attached_offer_is_never_treated_as_archived():
    # archived_ids only lists offers this key can see in /offers/deleted; an offer that is
    # still attached in Keitaro stays active whatever that list says.
    new, _ = merge_fetch(base(), links((1, 60), (2, 40)), {2})
    assert new.rows[1] == active(2, 40)


def test_keitaro_order_wins_and_removed_rows_keep_their_place_after_their_predecessor():
    old = base(active(1, 25), active(2, 25), active(3, 25), active(4, 25))
    new, _ = merge_fetch(old, links((4, 50), (1, 50)), set())
    # 2 and 3 followed 1 before; they still follow it
    assert [r.offer_id for r in new.rows] == [4, 1, 2, 3]


def test_removed_first_row_stays_first():
    old = base(active(1, 50), active(2, 50))
    new, _ = merge_fetch(old, links((2, 100)), set())
    assert [r.offer_id for r in new.rows] == [1, 2]


def test_pinned_offer_takes_keitaros_share_and_keeps_its_pin_age():
    old = base(active(1, 60, pin=Pin(60, 3)), active(2, 40), next_pin_seq=4)
    new, _ = merge_fetch(old, links((1, 70), (2, 30)), set())
    assert new == base(active(1, 70, pin=Pin(70, 3)), active(2, 30), next_pin_seq=4)


def test_dormant_pin_survives_a_fetch_and_follows_a_return_in_keitaro():
    old = base(active(1, 100), removed(2, RemovedBy.LOCAL, pin=Pin(30, 1)), next_pin_seq=2)
    new, _ = merge_fetch(old, links((1, 80), (2, 20)), set())
    assert new.rows[1] == active(2, 20, pin=Pin(20, 1))


# --- pending ops replayed on the new base --------------------------------------------------


def fetched(old: FlowState, kt: list[OfferLink], ops: list) -> tuple[FlowState, FlowState,
                                                                     list[str]]:
    new_base, _ = merge_fetch(old, kt, set())
    working, notes = replay(new_base, ops)
    return new_base, working, notes


def test_pending_remove_of_an_offer_keitaro_already_removed_is_a_no_op():
    old = base(active(1, 50), active(2, 50))
    new_base, working, notes = fetched(old, links((1, 100)), [Remove(offer_id=2)])
    assert working == new_base
    assert notes == ["Offer [2] is already removed."]


def test_pending_add_of_an_offer_keitaro_already_added_is_a_no_op():
    old = base(active(1, 100))
    new_base, working, notes = fetched(old, links((1, 50), (2, 50)), [Add(offer_id=2)])
    assert working == new_base
    assert notes == ["Offer [2] is already in this flow."]


def test_pending_share_edit_on_an_offer_keitaro_removed_is_dropped():
    old = base(active(1, 50), active(2, 50))
    new_base, working, notes = fetched(old, links((1, 100)), [SetShare(offer_id=2, share=70)])
    assert working == new_base
    assert notes == ["Offer [2] is removed; bring it back first."]


def test_pending_bring_back_of_an_offer_now_archived_is_a_no_op():
    old = base(active(1, 100), removed(2, RemovedBy.LOCAL))
    new_base, _ = merge_fetch(old, links((1, 100)), {2})
    working, notes = replay(new_base, [BringBack(offer_id=2)])
    assert working == new_base
    assert notes == ["Offer [2] is archived in Keitaro and can't be restored."]


def test_pending_edits_unrelated_to_keitaros_change_stay_on_top():
    old = base(active(1, 50), active(2, 50))
    _, working, _ = fetched(old, links((1, 50), (2, 25), (3, 25)), [Remove(offer_id=1)])
    assert [(r.offer_id, r.share) for r in working.rows] == [(1, 0), (2, 50), (3, 50)]


def test_replaying_ops_that_keitaro_already_has_is_clean():
    # crash after PUT, before our commit: Keitaro has the result, pending still has the ops
    old = base(active(1, 34), active(2, 33), active(3, 33))
    new_base, working, _ = fetched(old, links((1, 50), (2, 50)), [Remove(offer_id=3)])
    assert not diff(new_base, working).dirty


# --- signature -----------------------------------------------------------------------------


def test_signature_is_the_ordered_keitaro_offer_list():
    assert signature(links((1, 60), (2, 40))) == [[1, 60, "active"], [2, 40, "active"]]
    assert signature(links((1, 60), (2, 40))) != signature(links((2, 40), (1, 60)))


# --- invariant -----------------------------------------------------------------------------


def _splits(n: int) -> st.SearchStrategy[list[int]]:
    cuts = st.lists(st.integers(0, 100), min_size=n - 1, max_size=n - 1).map(sorted)
    return cuts.map(lambda c: [b - a for a, b in zip([0, *c], [*c, 100], strict=True)])


_op = st.one_of(
    st.builds(Remove, offer_id=st.integers(1, 6)),
    st.builds(BringBack, offer_id=st.integers(1, 6)),
    st.builds(Add, offer_id=st.integers(1, 6)),
    st.builds(SetShare, offer_id=st.integers(1, 6), share=st.integers(0, 100)),
    st.builds(TogglePin, offer_id=st.integers(1, 6)),
)


@given(st.integers(1, 5).flatmap(_splits), st.lists(_op, max_size=12))
def test_any_op_sequence_keeps_active_shares_at_100(start, ops):
    state, _ = merge_fetch(base(), links(*enumerate(start, start=1)), set())
    working, _ = replay(state, ops)
    live = [r.share for r in working.rows if r.active]
    assert not live or sum(live) == 100
