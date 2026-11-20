"""Stats & trends maths (vision .claude/vision/stats_trends.md §3, Rules 1-5, §4 windows)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.stats import (
    Cell,
    Counts,
    DayRow,
    Trend,
    Verdict,
    noise_band,
    report_range,
    span,
    summarize,
    trend,
)

TODAY = date(2026, 11, 20)


def d(offset: int) -> date:
    return TODAY + timedelta(days=offset)


def c(clicks=0, leads=0, sales=0, rejected=0, lead_rev="0", sale_rev="0") -> Counts:
    return Counts(clicks, leads, sales, rejected, Decimal(lead_rev), Decimal(sale_rev))


def row(day: int, counts: Counts, offer: int | None = 1, stream: int = 10) -> DayRow:
    return DayRow(stream_id=stream, offer_id=offer, day=d(day), counts=counts)


# --- Counts ------------------------------------------------------------------------------


def test_counts_add_field_by_field():
    a = Counts(1, 2, 3, 4, Decimal("5.5"), Decimal("6.25"))
    b = Counts(10, 20, 30, 40, Decimal(50), Decimal(60))
    assert a + b == Counts(11, 22, 33, 44, Decimal("55.5"), Decimal("66.25"))


def test_conversions_are_leads_plus_sales_not_rejected():
    assert c(leads=3, sales=4, rejected=100).conversions == 7


def test_revenue_is_lead_plus_sale_revenue():
    assert c(lead_rev="2.5", sale_rev="4").revenue == Decimal("6.5")


# --- periods -----------------------------------------------------------------------------


def test_today_is_the_partial_current_day():
    assert span("today", TODAY) == (TODAY, TODAY)


@pytest.mark.parametrize("n", [7, 14, 30])
def test_n_days_are_complete_days_ending_yesterday(n):
    assert span(n, TODAY) == (d(-n), d(-1))


@pytest.mark.parametrize(("period", "back"), [("today", 16), (7, 16), (14, 16), (30, 30)])
def test_report_range_always_covers_the_trend_window_and_today(period, back):
    assert report_range(period, TODAY) == (d(-back), TODAY)


# --- ratios: sum first, divide once (Rule 1) ---------------------------------------------


def test_cr_sums_before_dividing():
    rows = [row(-2, c(clicks=10, leads=3)), row(-1, c(clicks=1000, sales=50))]
    cell = summarize(rows, 7, TODAY)[10].offers[1].cell
    assert cell.cr == pytest.approx(53 / 1010)  # 5.2 %, not the 17.5 % mean of 30 % and 5 %


def test_epc_beats_cr_when_payout_differs():
    a = Cell.of(c(clicks=100, sales=3, sale_rev="75"), flow_clicks=200)
    b = Cell.of(c(clicks=100, sales=5, sale_rev="50"), flow_clicks=200)
    assert (a.epc, b.epc) == (Decimal("0.75"), Decimal("0.5"))
    assert a.cr < b.cr


def test_epc_counts_lead_and_sale_revenue():
    cell = Cell.of(c(clicks=4, leads=1, sales=1, lead_rev="1", sale_rev="1"), flow_clicks=4)
    assert cell.epc == Decimal("0.5")


@pytest.mark.parametrize(
    ("leads", "sales", "rejected", "cr"),
    [(40, 0, 0, 0.040), (22, 18, 0, 0.040), (0, 26, 14, 0.026)],
)
def test_lag_moves_statuses_and_cr_counts_leads_and_sales(leads, sales, rejected, cr):
    cell = Cell.of(c(clicks=1000, leads=leads, sales=sales, rejected=rejected), flow_clicks=1000)
    assert cell.cr == pytest.approx(cr)


def test_pending_share_is_leads_over_all_postbacks():
    cell = Cell.of(c(clicks=100, leads=2, sales=5, rejected=3), flow_clicks=100)
    assert cell.pending == pytest.approx(0.2)


def test_zero_clicks_is_none_not_zero():
    cell = Cell.of(Counts(), flow_clicks=0)
    assert (cell.epc, cell.cr, cell.pending, cell.split) == (None, None, None, None)


def test_split_is_offer_clicks_over_all_flow_clicks():
    rows = [row(-1, c(clicks=60)), row(-1, c(clicks=30), offer=2), row(-1, c(clicks=10), None)]
    flow = summarize(rows, 7, TODAY)[10]
    assert flow.offers[1].cell.split == pytest.approx(0.6)
    assert flow.offers[2].cell.split == pytest.approx(0.3)
    assert flow.totals.split is None


def test_flow_epc_is_the_click_weighted_blend_not_the_mean():
    rows = [row(-1, c(clicks=900, sales=9, sale_rev="90")),  # EPC 0.10
            row(-1, c(clicks=100, sales=10, sale_rev="100"), offer=2)]  # EPC 1.00
    assert summarize(rows, 7, TODAY)[10].totals.epc == Decimal("0.19")


# --- what flow totals include (Rule 5) ---------------------------------------------------


def test_flow_totals_include_no_offer_rows_and_period_only():
    rows = [row(-1, c(clicks=5)), row(-1, c(clicks=7), None), row(-3, c(clicks=11), offer=99),
            row(-8, c(clicks=1000)), row(0, c(clicks=1000))]
    flow = summarize(rows, 7, TODAY)[10]
    assert flow.totals.counts.clicks == 23
    assert set(flow.offers) == {1, 99}


def test_offer_with_traffic_only_outside_the_period_is_listed_with_zero_clicks():
    flow = summarize([row(-12, c(clicks=50))], "today", TODAY)[10]
    assert flow.offers[1].cell.counts.clicks == 0
    assert flow.offers[1].cell.cr is None


def test_flows_are_kept_apart():
    result = summarize([row(-1, c(clicks=5)), row(-1, c(clicks=9), stream=11)], 7, TODAY)
    assert (result[10].totals.counts.clicks, result[11].totals.counts.clicks) == (5, 9)


def test_today_period_reads_only_today():
    rows = [row(0, c(clicks=3)), row(-1, c(clicks=100))]
    assert summarize(rows, "today", TODAY)[10].totals.counts.clicks == 3


# --- noise band and trend (Rule 3, §4) ---------------------------------------------------


def test_noise_band_worked_numbers():
    assert noise_band(90, 75) == pytest.approx(0.3127, abs=1e-4)
    assert noise_band(900, 750) == pytest.approx(0.0989, abs=1e-4)


def week(offset_first: int, clicks_per_day: int, sales_per_day: int, payout="10") -> list[DayRow]:
    rev = str(Decimal(payout) * sales_per_day)
    return [row(offset_first - i, c(clicks=clicks_per_day, sales=sales_per_day, sale_rev=rev))
            for i in range(7)]


def test_older_week_is_days_minus_16_to_minus_10_and_newer_minus_9_to_minus_3():
    t = trend(week(-10, 100, 10) + week(-3, 200, 30), TODAY)
    assert (t.older.clicks, t.newer.clicks) == (700, 1400)


def test_days_outside_both_weeks_are_ignored():
    t = trend(week(-10, 100, 10) + week(-3, 100, 10) + [row(-2, c(clicks=999, sales=999)),
              row(-17, c(clicks=999, sales=999))], TODAY)
    assert (t.older.clicks, t.newer.clicks) == (700, 700)


def test_change_is_relative_epc_and_real_beyond_the_band():
    t = trend(week(-10, 1000, 30) + week(-3, 1000, 15), TODAY)  # 210 → 105 conv, EPC halves
    assert t.change == pytest.approx(-0.5)
    assert t.band == pytest.approx(noise_band(210, 105))
    assert t.verdict is Verdict.DOWN


def test_rise_beyond_the_band_is_up():
    assert trend(week(-10, 1000, 15) + week(-3, 1000, 30), TODAY).verdict is Verdict.UP


def test_minus_17_percent_at_low_volume_is_within_noise():
    older = week(-10, 300, 12)  # 84 conv
    newer = [row(-3 - i, c(clicks=300, sales=s, sale_rev=str(10 * s)))
             for i, s in enumerate([10, 10, 10, 10, 10, 10, 10])]  # 70 conv, −16.7 %
    t = trend(older + newer, TODAY)
    assert t.change == pytest.approx(70 / 84 - 1)
    assert t.verdict is Verdict.NOISE


def test_change_equal_to_the_band_is_real():
    assert Trend.judge(change=0.25, band=0.25) is Verdict.UP
    assert Trend.judge(change=-0.25, band=0.25) is Verdict.DOWN
    assert Trend.judge(change=0.2499, band=0.25) is Verdict.NOISE


@pytest.mark.parametrize(
    ("older", "newer"),
    [(week(-10, 14, 1), week(-3, 100, 5)),     # 98 clicks in the older week
     (week(-10, 100, 5), week(-3, 14, 1)),     # 98 clicks in the newer week
     (week(-10, 100, 0), week(-3, 100, 5)),    # no conversions in the older week
     (week(-10, 100, 5), week(-3, 100, 0))],   # no conversions in the newer week
)
def test_thin_weeks_read_not_enough_traffic(older, newer):
    t = trend(older + newer, TODAY)
    assert (t.verdict, t.change, t.band) == (Verdict.THIN, None, None)


def test_exactly_100_clicks_is_enough():
    t = trend(week(-10, 100, 0) + [row(-16, c(clicks=0, sales=7, sale_rev="70"))]
              + week(-3, 100, 1), TODAY)
    assert t.older.clicks == 700 and t.verdict is not Verdict.THIN
    weekly_100 = [row(-10, c(clicks=100, sales=5, sale_rev="50"))]
    t = trend(weekly_100 + [row(-3, c(clicks=100, sales=5, sale_rev="50"))], TODAY)
    assert t.verdict is Verdict.NOISE


def test_older_week_without_revenue_reads_not_enough_traffic():
    t = trend(week(-10, 100, 5, payout="0") + week(-3, 100, 5), TODAY)
    assert t.verdict is Verdict.THIN


def test_sparkline_is_daily_epc_for_days_minus_14_to_minus_1():
    rows = [row(-14, c(clicks=10, sales=1, sale_rev="5")), row(-1, c(clicks=4, sale_rev="2")),
            row(-15, c(clicks=1, sale_rev="99")), row(0, c(clicks=1, sale_rev="99"))]
    daily = trend(rows, TODAY).daily_epc
    assert len(daily) == 14
    assert daily[0] == Decimal("0.5") and daily[-1] == Decimal("0.5")
    assert daily[1:-1] == (None,) * 12


def test_trend_rejects_inconsistent_states():
    with pytest.raises(ValueError):
        Trend(Verdict.THIN, (), Counts(), Counts(), change=0.1, band=None)
    with pytest.raises(ValueError):
        Trend(Verdict.THIN, (), Counts(), Counts(), change=None, band=0.1)
    with pytest.raises(ValueError):
        Trend(Verdict.UP, (), Counts(), Counts(), change=None, band=None)


def test_offer_trend_ignores_other_offers_and_flows():
    rows = (week(-10, 1000, 30) + week(-3, 1000, 15)
            + [row(-5, c(clicks=5000, sales=900, sale_rev="9000"), offer=2),
               row(-5, c(clicks=5000, sales=900, sale_rev="9000"), stream=11)])
    assert summarize(rows, 7, TODAY)[10].offers[1].trend.newer.clicks == 7000


# --- properties --------------------------------------------------------------------------

money = st.decimals(min_value=0, max_value=1000, places=2)
counts = st.builds(Counts, st.integers(0, 500), st.integers(0, 50), st.integers(0, 50),
                   st.integers(0, 50), money, money)
rows_st = st.lists(
    st.builds(DayRow, st.sampled_from([10, 11]), st.sampled_from([1, 2, None]),
              st.integers(-20, 0).map(d), counts),
    max_size=30,
)
periods = st.sampled_from(["today", 7, 14, 30])


def split_row(r: DayRow, k: float) -> list[DayRow]:
    def part(n):
        return int(n * k)
    a = Counts(part(r.counts.clicks), part(r.counts.leads), part(r.counts.sales),
               part(r.counts.rejected), (r.counts.lead_revenue / 2).quantize(Decimal("0.001")),
               (r.counts.sale_revenue / 2).quantize(Decimal("0.001")))
    b = Counts(r.counts.clicks - a.clicks, r.counts.leads - a.leads, r.counts.sales - a.sales,
               r.counts.rejected - a.rejected, r.counts.lead_revenue - a.lead_revenue,
               r.counts.sale_revenue - a.sale_revenue)
    return [DayRow(r.stream_id, r.offer_id, r.day, a), DayRow(r.stream_id, r.offer_id, r.day, b)]


@given(rows_st, periods, st.floats(0, 1))
def test_splitting_a_row_changes_nothing(rows, period, k):
    split = [part for r in rows for part in split_row(r, k)]
    assert summarize(split, period, TODAY) == summarize(rows, period, TODAY)


@given(rows_st, periods, st.randoms())
def test_row_order_does_not_matter(rows, period, rnd):
    shuffled = list(rows)
    rnd.shuffle(shuffled)
    assert summarize(shuffled, period, TODAY) == summarize(rows, period, TODAY)


@given(rows_st, periods)
def test_flow_totals_are_offers_plus_no_offer_rows(rows, period):
    lo, hi = span(period, TODAY)
    for stream, flow in summarize(rows, period, TODAY).items():
        offers = sum((o.cell.counts for o in flow.offers.values()), Counts())
        no_offer = sum((r.counts for r in rows if r.stream_id == stream and r.offer_id is None
                        and lo <= r.day <= hi), Counts())
        assert flow.totals.counts == offers + no_offer


@given(counts, st.integers(0, 1000))
def test_a_ratio_is_none_exactly_when_its_denominator_is_zero(k, extra):
    cell = Cell.of(k, flow_clicks=k.clicks + extra)
    assert (cell.cr is None) == (cell.epc is None) == (k.clicks == 0)
    assert (cell.pending is None) == (k.leads + k.sales + k.rejected == 0)
    assert (cell.split is None) == (k.clicks + extra == 0)


@given(rows_st, periods)
def test_splits_stay_within_the_flow(rows, period):
    for flow in summarize(rows, period, TODAY).values():
        for o in flow.offers.values():
            assert o.cell.split is None or 0 <= o.cell.split <= 1
        assert sum(o.cell.counts.clicks for o in flow.offers.values()) <= flow.totals.counts.clicks


@given(st.integers(1, 2000), st.integers(1, 2000), st.integers(2, 10))
def test_band_shrinks_as_counts_grow(c1, c2, k):
    assert noise_band(c1 * k, c2 * k) < noise_band(c1, c2)


@given(rows_st, st.lists(st.builds(DayRow, st.just(10), st.just(1),
                                   st.integers(-2, 0).map(d), counts), max_size=6))
def test_verdict_ignores_the_two_unsettled_days_and_today(rows, recent):
    base = [r for r in rows if r.day < d(-2)]
    assert trend(base + recent, TODAY).verdict == trend(base, TODAY).verdict
