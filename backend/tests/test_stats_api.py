"""GET /api/campaigns/{id}/stats: the beta switch, periods, the oracle, failures, the cache."""

from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest

from app.api import deps
from app.api.deps import KeyedTtlCache
from app.domain.stats import Counts
from app.keitaro.client import KeitaroError, UnreadableReport
from app.main import app, create_app
from app.services.stats import unavailable_reason
from tests.local import LocalClient
from tests.test_app_modes import _settings

TODAY = date(2026, 11, 20)
CID, FLOW, OTHER_FLOW = 42, 10, 11


def d(offset: int) -> date:
    return TODAY + timedelta(days=offset)


def k(clicks=0, leads=0, sales=0, rejected=0, lead_rev="0", sale_rev="0") -> Counts:
    return Counts(clicks, leads, sales, rejected, Decimal(lead_rev), Decimal(sale_rev))


@pytest.fixture
def stats(api, settings):
    """The shared api client with the beta on and a fixed today."""
    app.dependency_overrides[deps.get_settings] = lambda: settings.model_copy(
        update={"stats_beta": True})
    app.dependency_overrides[deps.get_today] = lambda: TODAY
    return api


def test_beta_off_answers_disabled_and_never_calls_keitaro(api, fake):
    resp = api.get(f"/api/campaigns/{CID}/stats?period=7")
    assert resp.json() == {"status": "disabled"}
    assert not [r for r in fake.requests if r.url.path.endswith("/report/build")]


@pytest.mark.parametrize("period", ["today", "7", "14", "30"])
def test_every_period_is_accepted(stats, period):
    resp = stats.get(f"/api/campaigns/{CID}/stats?period={period}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["period"] == period


def test_an_unknown_period_is_refused(stats):
    assert stats.get(f"/api/campaigns/{CID}/stats?period=5").status_code == 422


def test_the_request_covers_the_trend_window_in_the_configured_timezone(stats, fake):
    stats.get(f"/api/campaigns/{CID}/stats?period=today")
    body = next(r for r in fake.requests if r.url.path.endswith("/report/build")).content
    assert b'"from":"2026-11-04"' in body.replace(b" ", b"")
    assert b'"to":"2026-11-20"' in body.replace(b" ", b"")
    assert b'"timezone":"UTC"' in body.replace(b" ", b"")


def test_oracle_numbers_computed_by_hand(stats, fake):
    fake.record(CID, FLOW, 1, d(-1), k(600, 2, 10, 4, "20", "100"))
    fake.record(CID, FLOW, 2, d(-2), k(300, 0, 3, 0, "0", "45"))
    fake.record(CID, FLOW, None, d(-1), k(100))
    fake.record(CID, FLOW, 1, d(-9), k(1, 0, 1, 0, "0", "999"))  # outside 7 days
    fake.record(CID, OTHER_FLOW, 3, d(-1), k(50, 0, 1, 0, "0", "5"))
    body = stats.get(f"/api/campaigns/{CID}/stats?period=7").json()

    assert (body["as_of"], body["timezone"], body["currency"]) == ("2026-11-20", "UTC", "$")
    flow = next(f for f in body["flows"] if f["stream_id"] == FLOW)
    assert flow["totals"] == {
        "clicks": 1000, "leads": 2, "sales": 13, "rejected": 4, "conversions": 15,
        "revenue": "165.0000", "epc": "0.1650", "cr": pytest.approx(0.015),
        "pending": pytest.approx(2 / 19), "split": None}
    one = next(o for o in flow["offers"] if o["offer_id"] == 1)
    assert one["cell"]["epc"] == "0.2000"  # 120 / 600
    assert one["cell"]["split"] == pytest.approx(0.6)
    assert one["trend"]["verdict"] == "not_enough_traffic"
    assert (one["trend"]["change"], one["trend"]["band"]) == (None, None)
    assert len(one["trend"]["daily_epc"]) == 14
    assert one["trend"]["daily_epc"][-1] == "0.2000"
    assert one["trend"]["daily_epc"][0] is None


def test_flow_totals_match_keitaros_own_totals_row(stats, fake):
    fake.record(CID, FLOW, 1, d(-3), k(321, 4, 7, 2, "8", "70"))
    fake.record(CID, FLOW, None, d(-2), k(13))
    fake.record(CID, OTHER_FLOW, 5, d(-1), k(77, 1, 2, 0, "1", "2"))
    body = stats.get(f"/api/campaigns/{CID}/stats?period=7").json()
    totals = fake.handle(httpx.Request("POST", "https://f.invalid/admin_api/v1/report/build", json={
        "range": {"from": str(d(-7)), "to": str(d(-1)), "timezone": "UTC"}, "dimensions": [],
        "measures": ["clicks", "leads", "sales"],
        "filters": [{"name": "campaign_id", "operator": "EQUALS", "expression": CID}]})).json()
    row = totals["rows"][0]
    summed = {m: sum(f["totals"][m] for f in body["flows"]) for m in ("clicks", "leads", "sales")}
    assert summed == row
    flow_cr = sum(f["totals"]["conversions"] for f in body["flows"]) / row["clicks"]
    assert flow_cr == pytest.approx((row["leads"] + row["sales"]) / row["clicks"])


def test_a_trend_with_real_weeks_reports_change_and_band(stats, fake):
    for day in range(-16, -9):
        fake.record(CID, FLOW, 1, d(day), k(1000, 0, 30, 0, "0", "300"))
    for day in range(-9, -2):
        fake.record(CID, FLOW, 1, d(day), k(1000, 0, 15, 0, "0", "150"))
    trend = stats.get(f"/api/campaigns/{CID}/stats?period=7").json()["flows"][0]["offers"][0][
        "trend"]
    assert trend["verdict"] == "down"
    assert trend["change"] == pytest.approx(-0.5)
    assert trend["older"] == {"clicks": 7000, "conversions": 210, "epc": "0.3000"}
    assert trend["newer"] == {"clicks": 7000, "conversions": 105, "epc": "0.1500"}


@pytest.mark.parametrize(("status", "reason"), [
    (403, "this API key may not read reports"),
    (503, "Keitaro didn't answer in time"),
    (500, "Keitaro didn't answer in time"),
    (499, "Keitaro answered 499"),
    (400, "Keitaro answered 400"),
])
def test_a_keitaro_failure_is_unavailable_with_a_reason(stats, fake, status, reason):
    fake.fail_next("POST", "/report/build", status, "nope")
    assert stats.get(f"/api/campaigns/{CID}/stats?period=7").json() == {
        "status": "unavailable", "reason": reason}


def test_results_are_cached_per_campaign_and_period_until_refresh(stats, fake):
    fake.record(CID, FLOW, 1, d(-1), k(10))
    url = f"/api/campaigns/{CID}/stats?period=7"
    assert stats.get(url).json()["flows"][0]["totals"]["clicks"] == 10
    fake.record(CID, FLOW, 1, d(-1), k(20))
    assert stats.get(url).json()["flows"][0]["totals"]["clicks"] == 10
    assert stats.get(url + "&refresh=true").json()["flows"][0]["totals"]["clicks"] == 20
    assert stats.get(url).json()["flows"][0]["totals"]["clicks"] == 20
    assert stats.get(f"/api/campaigns/{CID}/stats?period=14").json()["flows"][0]["totals"][
        "clicks"] == 20


def test_an_unreachable_tracker_is_reported_as_not_answering():
    assert unavailable_reason(KeitaroError(0, "connect failed")) == "Keitaro didn't answer in time"
    assert unavailable_reason(KeitaroError(1, "odd")) == "Keitaro answered 1"


def test_an_unreadable_report_says_so():
    assert unavailable_reason(UnreadableReport("no rows")) == (
        "Keitaro sent a report this app can't read")


def test_a_refresh_drops_every_cached_period_of_that_campaign(stats, fake):
    fake.record(CID, FLOW, 1, d(-1), k(10))
    fake.record(CID + 1, FLOW + 5, 1, d(-1), k(10))
    clicks = lambda cid, p, extra="": stats.get(
        f"/api/campaigns/{cid}/stats?period={p}{extra}").json()["flows"][0]["totals"]["clicks"]
    assert (clicks(CID, 7), clicks(CID, 30), clicks(CID + 1, 7)) == (10, 10, 10)
    fake.record(CID, FLOW, 1, d(-1), k(20))
    fake.record(CID + 1, FLOW + 5, 1, d(-1), k(20))
    assert clicks(CID, 30, "&refresh=true") == 20
    assert clicks(CID, 7) == 20  # switching period right after a push shows fresh numbers
    assert clicks(CID + 1, 7) == 10  # other campaigns keep their cache


def test_traffic_control_refuses_absurd_sizes(tmp_path):
    api = beta_app(tmp_path)
    for body in ({"days": -1}, {"days": 400}, {"clicks_per_day": -5},
                 {"clicks_per_day": 2_000_000}):
        assert api.post("/api/_fake/traffic", json={"campaign_id": 1, **body}).status_code == 422


def test_a_failure_is_not_cached(stats, fake):
    fake.fail_next("POST", "/report/build", 503, "down")
    url = f"/api/campaigns/{CID}/stats?period=7"
    assert stats.get(url).json()["status"] == "unavailable"
    assert stats.get(url).json()["status"] == "ok"


def test_status_is_required_on_every_union_member():
    schema = app.openapi()["components"]["schemas"]
    for name in ("StatsDisabled", "StatsUnavailable", "StatsOk"):
        assert "status" in schema[name]["required"]


def test_keyed_cache_drops_matching_keys():
    cache = KeyedTtlCache(60)
    for key in [(1, "7"), (1, "30"), (2, "7")]:
        cache.put(key, key)
    cache.drop(lambda key: key[0] == 1)
    assert [cache.get(k) for k in [(1, "7"), (1, "30"), (2, "7")]] == [None, None, (2, "7")]


def test_keyed_cache_keeps_keys_apart_and_expires():
    now = [0.0]
    cache = KeyedTtlCache(60, clock=lambda: now[0])
    cache.put("a", 1)
    assert (cache.get("a"), cache.get("b")) == (1, None)
    now[0] = 61
    assert cache.get("a") is None
    cache.put("c", 3)
    assert "a" not in cache._items  # expired keys go, so a long-running server doesn't grow
    cache.put("a", 2)
    cache.clear()
    assert cache.get("a") is None


# --- fake mode: controls and the demo -----------------------------------------------------


def beta_app(tmp_path) -> LocalClient:
    return LocalClient(create_app(_settings(tmp_path, keitaro_fake=True, stats_beta=True)))


def test_fake_mode_exposes_the_fake_and_beta_off_sends_no_report(tmp_path):
    built = create_app(_settings(tmp_path, keitaro_fake=True))
    api = LocalClient(built)
    cid = api.get("/api/campaigns?q=demo").json()[0]["id"]
    assert api.get(f"/api/campaigns/{cid}/stats").json() == {"status": "disabled"}
    assert not [r for r in built.state.fake.requests if r.url.path.endswith("/report/build")]


def test_demo_campaign_shows_a_rise_a_quiet_drop_and_a_flat_offer(tmp_path):
    api = beta_app(tmp_path)
    cid = api.get("/api/campaigns?q=demo").json()[0]["id"]
    body = api.get(f"/api/campaigns/{cid}/stats?period=7").json()
    offers = {o["offer_id"]: o["trend"] for f in body["flows"] for o in f["offers"]}
    assert offers[3749]["verdict"] == "up"
    assert offers[3717]["verdict"] == "within_noise"
    assert -0.25 < offers[3717]["change"] < -0.08  # looks scary, and the screen declines it
    assert 50 < offers[3717]["newer"]["conversions"] < 110
    assert offers[11111]["verdict"] == "within_noise"
    today = api.get(f"/api/campaigns/{cid}/stats?period=today").json()
    assert all(f["totals"]["pending"] > 0.5 for f in today["flows"])  # the demo has lag on


def test_traffic_controls_write_traffic_and_clear_the_cache(tmp_path):
    api = beta_app(tmp_path)
    cid = api.get("/api/campaigns?q=demo").json()[0]["id"]
    url = f"/api/campaigns/{cid}/stats?period=7"
    before = api.get(url).json()["flows"][0]["totals"]["clicks"]
    assert api.delete(f"/api/_fake/traffic?campaign_id={cid}").status_code == 204
    assert api.get(url).json()["flows"] == []
    assert api.put("/api/_fake/offers/3749/profile",
                   json={"cr_all": 1.0, "approve": 1.0, "payout": "2"}).status_code == 204
    assert api.post("/api/_fake/traffic", json={"campaign_id": cid, "days": 7,
                                                "clicks_per_day": 100}).status_code == 204
    after = api.get(url).json()["flows"][0]
    assert after["totals"]["clicks"] == 700 != before
    one = next(o for o in after["offers"] if o["offer_id"] == 3749)
    assert one["cell"]["epc"] == "2.0000"  # every click converts and is paid $2


def test_fail_next_makes_the_next_report_unavailable(tmp_path):
    api = beta_app(tmp_path)
    cid = api.get("/api/campaigns?q=demo").json()[0]["id"]
    url = f"/api/campaigns/{cid}/stats?period=7"
    assert api.get(url).json()["status"] == "ok"
    assert api.post("/api/_fake/fail-next", json={"status": 503}).status_code == 204
    assert api.get(url).json()["status"] == "unavailable"
    assert api.get(url).json()["status"] == "ok"
