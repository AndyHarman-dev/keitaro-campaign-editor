"""Share allocation and staged operations (vision §2 'Share & pin rules', §5)."""

import pytest

from app.domain.flow import (
    Add,
    BringBack,
    FlowState,
    InvalidPush,
    OfferRow,
    Pin,
    Remove,
    RemovedBy,
    RowStatus,
    SetShare,
    TogglePin,
    apply,
    diff,
    forget,
    push_plan,
    replay,
)


def flow(*shares: int, pins: dict[int, int] | None = None) -> FlowState:
    """Active rows with ids 1..n and the given shares; pins maps id -> seq."""
    pins = pins or {}
    rows = tuple(
        OfferRow(
            offer_id=i,
            status=RowStatus.ACTIVE,
            share=s,
            pin=Pin(share=s, seq=pins[i]) if i in pins else None,
        )
        for i, s in enumerate(shares, start=1)
    )
    return FlowState(rows=rows, next_pin_seq=max(pins.values(), default=0) + 1)


def shares(state: FlowState) -> list[int]:
    return [r.share for r in state.rows]


def pinned(state: FlowState) -> list[int]:
    return [r.offer_id for r in state.rows if r.pin is not None and r.status is RowStatus.ACTIVE]


# --- construction rules: illegal rows cannot exist ---------------------------------------


def test_removed_row_cannot_hold_a_share():
    with pytest.raises(ValueError):
        OfferRow(offer_id=1, status=RowStatus.REMOVED, share=5, removed_by=RemovedBy.LOCAL)


def test_removed_row_must_say_who_removed_it():
    with pytest.raises(ValueError):
        OfferRow(offer_id=1, status=RowStatus.REMOVED, share=0)


def test_active_row_cannot_carry_removed_by():
    with pytest.raises(ValueError):
        OfferRow(offer_id=1, status=RowStatus.ACTIVE, share=10, removed_by=RemovedBy.LOCAL)


def test_active_row_cannot_be_archived():
    with pytest.raises(ValueError):
        OfferRow(offer_id=1, status=RowStatus.ACTIVE, share=10, archived=True)


@pytest.mark.parametrize("share", [-1, 101])
def test_share_must_be_a_percentage(share):
    with pytest.raises(ValueError):
        OfferRow(offer_id=1, status=RowStatus.ACTIVE, share=share)


def test_active_pinned_row_shows_its_pinned_share():
    with pytest.raises(ValueError):
        OfferRow(offer_id=1, status=RowStatus.ACTIVE, share=30, pin=Pin(share=40, seq=1))


def test_offer_ids_are_unique_in_a_flow():
    row = OfferRow(offer_id=1, status=RowStatus.ACTIVE, share=50)
    with pytest.raises(ValueError):
        FlowState(rows=(row, row), next_pin_seq=1)


# --- allocation ----------------------------------------------------------------------------


def test_adding_a_third_offer_splits_equally_with_remainder_first():
    state, _ = apply(flow(50, 50), Add(offer_id=3))
    assert shares(state) == [34, 33, 33]


def test_pinned_share_is_kept_and_remainder_goes_to_first_unpinned_rows():
    # vision §2: 4 offers at 25 %, pin one at 25 %, remove one -> 25 pinned, 38 / 37
    state, _ = replay(flow(25, 25, 25, 25), [TogglePin(offer_id=2), Remove(offer_id=4)])
    assert shares(state) == [38, 25, 37, 0]
    assert pinned(state) == [2]


def test_inline_share_edit_auto_pins_and_rebalances_the_rest():
    state, notes = apply(flow(34, 33, 33), SetShare(offer_id=2, share=50))
    assert shares(state) == [25, 50, 25]
    assert pinned(state) == [2]
    assert notes == []


def test_oldest_pin_is_released_when_pins_exceed_100():
    start = flow(60, 20, 20, pins={1: 1})
    state, notes = apply(start, SetShare(offer_id=2, share=50))
    assert shares(state) == [25, 50, 25]
    assert pinned(state) == [2]
    assert notes == ["Auto-unpinned [1]: the pinned shares did not fit in 100%."]


def test_oldest_pin_is_released_when_every_row_is_pinned_and_total_is_not_100():
    start = flow(50, 50, pins={1: 1, 2: 2})
    state, notes = apply(start, SetShare(offer_id=2, share=40))
    assert shares(state) == [60, 40]
    assert pinned(state) == [2]
    assert notes == ["Auto-unpinned [1]: the pinned shares did not fit in 100%."]


def test_single_offer_set_below_100_takes_everything_back():
    state, notes = apply(flow(100), SetShare(offer_id=1, share=40))
    assert shares(state) == [100]
    assert pinned(state) == []
    assert notes == ["Auto-unpinned [1]: the pinned shares did not fit in 100%."]


def test_pins_totalling_exactly_100_leave_free_rows_at_zero():
    state, notes = apply(flow(50, 25, 25, pins={1: 1}), SetShare(offer_id=2, share=50))
    assert shares(state) == [50, 50, 0]
    assert pinned(state) == [1, 2]
    assert notes == []


def test_unpinning_returns_the_share_to_the_equal_split():
    state, _ = apply(flow(50, 25, 25, pins={1: 1}), TogglePin(offer_id=1))
    assert shares(state) == [34, 33, 33]
    assert pinned(state) == []


def test_pinning_freezes_the_current_share():
    state, _ = replay(flow(34, 33, 33), [TogglePin(offer_id=1), Remove(offer_id=3)])
    assert shares(state) == [34, 66, 0]


def test_pin_seq_grows_with_each_pin():
    state, _ = replay(flow(34, 33, 33), [TogglePin(offer_id=1), TogglePin(offer_id=2)])
    assert [r.pin.seq for r in state.rows[:2]] == [1, 2]
    assert state.next_pin_seq == 3


# --- remove / bring back -------------------------------------------------------------------


def test_remove_greys_out_at_zero_and_rebalances():
    state, _ = apply(flow(34, 33, 33), Remove(offer_id=1))
    assert shares(state) == [0, 50, 50]
    assert state.rows[0].status is RowStatus.REMOVED
    assert state.rows[0].removed_by is RemovedBy.LOCAL


def test_removed_pinned_offer_comes_back_with_its_pin():
    # vision §5: the pin goes away with the offer and comes back on Bring back
    removed, _ = replay(flow(34, 33, 33), [TogglePin(offer_id=1), Remove(offer_id=1)])
    assert shares(removed) == [0, 50, 50]
    assert pinned(removed) == []
    back, notes = apply(removed, BringBack(offer_id=1))
    assert shares(back) == [34, 33, 33]
    assert pinned(back) == [1]
    assert notes == ["Brought back [1] with its pin at 34%."]


def test_brought_back_pin_that_no_longer_fits_releases_the_oldest_pin():
    removed, _ = replay(
        flow(60, 20, 20),
        [TogglePin(offer_id=1), Remove(offer_id=1), SetShare(offer_id=2, share=50)],
    )
    back, notes = apply(removed, BringBack(offer_id=1))
    assert shares(back) == [25, 50, 25]
    assert pinned(back) == [2]
    assert notes[-1] == "Auto-unpinned [1]: the pinned shares did not fit in 100%."


def test_bring_back_without_pin_rejoins_the_equal_split():
    state, _ = replay(flow(34, 33, 33), [Remove(offer_id=2), BringBack(offer_id=2)])
    assert shares(state) == [34, 33, 33]


def test_archived_offer_cannot_be_brought_back():
    archived = OfferRow(
        offer_id=9, status=RowStatus.REMOVED, share=0, removed_by=RemovedBy.KEITARO,
        archived=True,
    )
    start = FlowState(rows=(*flow(100).rows, archived), next_pin_seq=1)
    state, notes = apply(start, BringBack(offer_id=9))
    assert state == start
    assert notes == ["Offer [9] is archived in Keitaro and can't be restored."]


def test_remove_of_an_already_removed_offer_changes_nothing():
    start, _ = apply(flow(50, 50), Remove(offer_id=1))
    state, notes = apply(start, Remove(offer_id=1))
    assert state == start
    assert notes == ["Offer [1] is already removed."]


def test_ops_on_unknown_offers_change_nothing():
    start = flow(50, 50)
    for op in (Remove(offer_id=7), BringBack(offer_id=7), SetShare(offer_id=7, share=5),
               TogglePin(offer_id=7)):
        state, notes = apply(start, op)
        assert state == start
        assert notes == ["Offer [7] is not in this flow."]


def test_share_edit_or_pin_on_a_removed_offer_changes_nothing():
    start, _ = apply(flow(50, 50), Remove(offer_id=1))
    for op in (SetShare(offer_id=1, share=5), TogglePin(offer_id=1)):
        state, notes = apply(start, op)
        assert state == start
        assert notes == ["Offer [1] is removed; bring it back first."]


# --- add -------------------------------------------------------------------------------------


def test_added_offer_goes_to_the_end():
    state, _ = apply(flow(100), Add(offer_id=5))
    assert [r.offer_id for r in state.rows] == [1, 5]
    assert shares(state) == [50, 50]
    assert state.rows[1].kt_state == "active"


def test_adding_an_offer_already_in_the_flow_changes_nothing():
    start = flow(50, 50)
    state, notes = apply(start, Add(offer_id=2))
    assert state == start
    assert notes == ["Offer [2] is already in this flow."]


def test_adding_a_removed_offer_brings_it_back():
    start, _ = apply(flow(50, 50), Remove(offer_id=2))
    state, _ = apply(start, Add(offer_id=2))
    assert shares(state) == [50, 50]
    assert state.rows[1].status is RowStatus.ACTIVE


def test_adding_an_archived_offer_changes_nothing():
    archived = OfferRow(
        offer_id=9, status=RowStatus.REMOVED, share=0, removed_by=RemovedBy.KEITARO,
        archived=True,
    )
    start = FlowState(rows=(*flow(100).rows, archived), next_pin_seq=1)
    state, notes = apply(start, Add(offer_id=9))
    assert state == start
    assert notes == ["Offer [9] is archived in Keitaro and can't be restored."]


# --- forget (archived rows leave the list for good, local only) -----------------------------


def test_forget_drops_an_archived_row():
    archived = OfferRow(
        offer_id=9, status=RowStatus.REMOVED, share=0, removed_by=RemovedBy.KEITARO,
        archived=True,
    )
    start = FlowState(rows=(*flow(100).rows, archived), next_pin_seq=1)
    assert forget(start, 9) == flow(100)


def test_forget_refuses_rows_that_are_not_archived():
    with pytest.raises(ValueError):
        forget(flow(100), 1)


# --- diff / dirty ----------------------------------------------------------------------------


def test_remove_then_bring_back_is_not_dirty():
    base = flow(34, 33, 33)
    working, _ = replay(base, [Remove(offer_id=2), BringBack(offer_id=2)])
    assert diff(base, working).changed == 0
    assert not diff(base, working).dirty


def test_diff_counts_changed_rows():
    base = flow(34, 33, 33)
    working, _ = replay(base, [Remove(offer_id=3), Add(offer_id=4)])
    # 34/33/0 + new 33: rows 1 and 2 keep their shares; row 3 removed, row 4 added
    assert diff(base, working).changed == 2


def test_diff_counts_pin_only_changes():
    base = flow(50, 50)
    working, _ = apply(base, TogglePin(offer_id=1))
    assert diff(base, working).changed == 1
    assert diff(base, working).dirty


# --- push plan -------------------------------------------------------------------------------


def test_push_plan_sends_active_rows_in_order_with_their_keitaro_state():
    rows = (
        OfferRow(offer_id=1, status=RowStatus.ACTIVE, share=60, kt_state="disabled"),
        OfferRow(offer_id=2, status=RowStatus.REMOVED, share=0, removed_by=RemovedBy.LOCAL),
        OfferRow(offer_id=3, status=RowStatus.ACTIVE, share=40),
    )
    plan = push_plan(FlowState(rows=rows, next_pin_seq=1))
    assert [(link.offer_id, link.share, link.state) for link in plan] == [
        (1, 60, "disabled"), (3, 40, "active"),
    ]


def test_push_plan_refuses_shares_that_do_not_total_100():
    with pytest.raises(InvalidPush):
        push_plan(flow(50, 40))


def test_push_plan_refuses_an_empty_flow():
    with pytest.raises(InvalidPush):
        push_plan(FlowState(rows=(), next_pin_seq=1))
