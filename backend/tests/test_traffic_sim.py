"""Fake traffic simulator, and the statistical checks that the noise band is calibrated.

Layer 4 of the plan's verification (.claude/plans/stats_trends.md). Everything is seeded, so
every run gives the same numbers; the seed loops are marked slow.
"""

from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest

from app.domain.stats import DayRow, Verdict, summarize, trend
from app.keitaro.fake import FakeKeitaro
from app.keitaro.traffic import OfferProfile, default_profile, simulate

TODAY = date(2026, 11, 20)
API = "https://fake.invalid/admin_api/v1"


def tracker(*shares: tuple[int, int]) -> tuple[FakeKeitaro, int, int]:
    """A campaign with a redirect flow and one offer flow holding (offer_id, share) pairs."""
    fake = FakeKeitaro()
    for oid, _ in shares:
        fake.add_offer(oid, f"Offer {oid}")
    cid = fake.handle(httpx.Request("POST", f"{API}/campaigns",
                                    json={"name": "c", "alias": "a"})).json()["id"]
    fake.handle(httpx.Request("POST", f"{API}/streams", json={
        "campaign_id": cid, "name": "Flow 1", "position": 1, "type": "forced"}))
    sid = fake.handle(httpx.Request("POST", f"{API}/streams", json={
        "campaign_id": cid, "name": "Flow 2", "position": 2, "type": "regular",
        "offers": [{"offer_id": o, "share": s, "state": "active"} for o, s in shares]})).json()["id"]
    return fake, cid, sid


def rows(fake: FakeKeitaro, cid: int) -> list[DayRow]:
    return [DayRow(s, o, d, k) for (c, s, o, d), k in fake.traffic.items() if c == cid]


def day(offset: int) -> date:
    return TODAY + timedelta(days=offset)


# --- shape --------------------------------------------------------------------------------


def test_profiles_default_from_the_offer_id_and_can_be_overridden():
    assert default_profile(3749) == default_profile(3749)
    assert default_profile(3749) != default_profile(3717)
    p = default_profile(3749)
    assert 0 < p.cr_all < 1 and 0 < p.approve < 1 and p.payout > 0
    fake, cid, _ = tracker((1, 100))
    fake.profiles[1] = OfferProfile(cr_all=0.0, approve=0.5, payout=Decimal(10))
    simulate(fake, cid, 3, 500, today=TODAY, seed=1)
    assert all(k.conversions == 0 for k in fake.traffic.values())


def test_clicks_follow_the_current_shares_exactly_and_skip_the_redirect_flow():
    fake, cid, sid = tracker((1, 60), (2, 20), (3, 20))
    simulate(fake, cid, 7, 1001, today=TODAY, seed=1)
    week = summarize(rows(fake, cid), 7, TODAY)
    assert set(week) == {sid}
    assert {o: s.cell.counts.clicks for o, s in week[sid].offers.items()} == {
        1: 7 * 601, 2: 7 * 200, 3: 7 * 200}


def test_paused_and_zero_share_offers_get_no_clicks():
    fake, cid, sid = tracker((1, 50), (2, 50), (3, 0), (4, 1))
    fake.streams[sid]["offers"][1]["state"] = "paused"
    simulate(fake, cid, 1, 100, today=TODAY, seed=1)
    assert {o for (c, s, o, d) in fake.traffic} == {1, 4}  # a 1% share still gets clicks


def test_a_flow_whose_offers_are_all_at_zero_gets_no_traffic():
    fake, cid, _ = tracker((1, 0))
    simulate(fake, cid, 1, 100, today=TODAY, seed=1, no_offer=0.5)
    assert fake.traffic == {}


def test_no_offer_fraction_and_partial_today():
    fake, cid, _ = tracker((1, 100))
    simulate(fake, cid, 2, 1000, today=TODAY, seed=1, no_offer=0.1, today_fraction=0.25)
    by_key = {(o, d): k.clicks for (c, s, o, d), k in fake.traffic.items()}
    assert by_key == {(1, day(-2)): 900, (None, day(-2)): 100, (1, day(-1)): 900,
                      (None, day(-1)): 100, (1, day(0)): 225, (None, day(0)): 25}


def test_money_is_booked_on_leads_and_sales_at_the_payout():
    fake, cid, _ = tracker((1, 100))
    fake.profiles[1] = OfferProfile(cr_all=0.1, approve=0.5, payout=Decimal("12.5"))
    simulate(fake, cid, 3, 2000, today=TODAY, seed=4, lag=True)
    for k in fake.traffic.values():
        assert k.lead_revenue == k.leads * Decimal("12.5")
        assert k.sale_revenue == k.sales * Decimal("12.5")
        assert k.postbacks <= k.clicks


def test_simulating_again_is_idempotent_and_replaces_those_days():
    fake, cid, sid = tracker((1, 100))
    simulate(fake, cid, 5, 300, today=TODAY, seed=9)
    first = dict(fake.traffic)
    simulate(fake, cid, 5, 300, today=TODAY, seed=9)
    assert fake.traffic == first
    simulate(fake, cid, 2, 10, today=TODAY, seed=9)
    assert fake.traffic[(cid, sid, 1, day(-1))].clicks == 10
    assert fake.traffic[(cid, sid, 1, day(-5))] == first[(cid, sid, 1, day(-5))]


def test_seed_changes_the_draws():
    a, cid, _ = tracker((1, 100))
    b, _, _ = tracker((1, 100))
    simulate(a, cid, 5, 3000, today=TODAY, seed=1)
    simulate(b, cid, 5, 3000, today=TODAY, seed=2)
    assert a.traffic != b.traffic


def test_lag_only_relabels_the_same_outcomes():
    """Same seed with and without lag: identical clicks and postbacks; lag only moves labels."""
    off, cid, _ = tracker((1, 100))
    on, _, _ = tracker((1, 100))
    simulate(off, cid, 10, 3000, today=TODAY, seed=5)
    simulate(on, cid, 10, 3000, today=TODAY, seed=5, lag=True)
    for key, k in off.traffic.items():
        lagged = on.traffic[key]
        assert (lagged.clicks, lagged.postbacks) == (k.clicks, k.postbacks)
        assert k.leads == 0
        assert lagged.sales <= k.sales and lagged.rejected <= k.rejected


def test_drift_is_a_weekly_ratio_and_the_rate_is_capped_at_one():
    fake, cid, sid = tracker((1, 100))
    fake.profiles[1] = OfferProfile(cr_all=0.9, approve=1.0, payout=Decimal(1))
    simulate(fake, cid, 15, 1000, today=TODAY, seed=3, drift={1: 1.0})
    assert all(k.postbacks <= k.clicks for k in fake.traffic.values())
    newest = fake.traffic[(cid, sid, 1, day(-1))]
    assert newest.postbacks == 1000  # 0.9 × 2^(14/7) = 3.6, capped at 1


# --- layer 4: statistics -------------------------------------------------------------------

STEADY = OfferProfile(cr_all=0.05, approve=0.6, payout=Decimal(20))


def one_offer_trend(seed: int, clicks: int, profile=STEADY, **kw):
    fake, cid, _ = tracker((1, 100))
    fake.profiles[1] = profile
    simulate(fake, cid, 16, clicks, today=TODAY, seed=seed, **kw)
    return trend(rows(fake, cid), TODAY)


@pytest.mark.slow
def test_band_false_positive_rate_is_at_most_ten_percent():
    verdicts = [one_offer_trend(seed, 300).verdict for seed in range(200)]
    flagged = sum(v in (Verdict.UP, Verdict.DOWN) for v in verdicts)
    assert Verdict.THIN not in verdicts
    assert flagged <= 20  # a 2σ band should flag about 5 %


@pytest.mark.slow
def test_a_forty_percent_weekly_drop_at_300_to_180_conversions_is_caught():
    profile = OfferProfile(cr_all=0.08, approve=0.6, payout=Decimal(20))
    trends = [one_offer_trend(seed, 1000, profile, drift={1: -0.4}) for seed in range(200)]
    assert 230 < sum(t.older.conversions for t in trends) / 200 < 320  # the stated volume
    assert sum(t.verdict is Verdict.DOWN for t in trends) >= 190


def test_profile_is_recovered_at_100k_clicks():
    fake, cid, sid = tracker((1, 100))
    fake.profiles[1] = STEADY
    simulate(fake, cid, 7, 14286, today=TODAY, seed=11)
    cell = summarize(rows(fake, cid), 7, TODAY)[sid].offers[1].cell
    sigma_cr = (0.03 * 0.97 / cell.counts.clicks) ** 0.5
    assert abs(cell.cr - 0.03) < 3 * sigma_cr
    assert abs(float(cell.epc) - 0.60) < 3 * 20 * sigma_cr


def test_lag_leaves_about_sixty_percent_of_yesterday_pending():
    fake, cid, _ = tracker((1, 100))
    fake.profiles[1] = STEADY
    simulate(fake, cid, 3, 10000, today=TODAY, seed=2, lag=True)
    yesterday = next(k for (c, s, o, d), k in fake.traffic.items() if d == day(-1))
    pending = yesterday.leads / yesterday.postbacks
    assert abs(pending - 0.6) < 3 * (0.24 / yesterday.postbacks) ** 0.5


@pytest.mark.slow
def test_lag_does_not_change_the_trend_beyond_its_small_tail():
    # The 2 % tail turns some rejected postbacks into paid leads. At 300 clicks a day that is
    # 0.8 ± 0.9 leads a week, ~1.6 % of EPC each, so the change would differ by ~2 % SD. At
    # 3,000 clicks a day the SD is ~0.65 % and the 0.03 tolerance sits at ~4.6σ.
    for seed in range(100):
        off = one_offer_trend(seed, 3000)
        on = one_offer_trend(seed, 3000, lag=True)
        assert abs(on.change - off.change) < 0.03
        if abs(abs(off.change) - off.band) > 0.03:
            assert on.verdict is off.verdict


def test_a_window_spanning_a_push_shows_the_blend():
    fake, cid, sid = tracker((1, 50), (2, 50))
    simulate(fake, cid, 14, 1000, today=TODAY, seed=1)
    fake.handle(httpx.Request("PUT", f"{API}/streams/{sid}", json={"offers": [
        {"offer_id": 1, "share": 80, "state": "active"},
        {"offer_id": 2, "share": 20, "state": "active"}]}))
    simulate(fake, cid, 7, 1000, today=TODAY, seed=2)
    week = summarize(rows(fake, cid), 7, TODAY)[sid].offers
    fortnight = summarize(rows(fake, cid), 14, TODAY)[sid].offers
    assert week[1].cell.split == pytest.approx(0.8, abs=0.02)
    assert fortnight[1].cell.split == pytest.approx(0.65, abs=0.02)
