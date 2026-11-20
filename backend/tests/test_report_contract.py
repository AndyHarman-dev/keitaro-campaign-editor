"""Report contract: KeitaroClient.report, lenient row parsing, and the fake's /report/build."""

import json
from datetime import date
from decimal import Decimal

import httpx
import pytest

from app.domain.stats import Counts, DayRow
from app.keitaro.client import KeitaroClient, KeitaroError
from app.keitaro.fake import REPORT_COLUMNS, FakeKeitaro
from app.keitaro.schemas import KtReportRow

API = "https://fake.invalid/admin_api/v1"
D1, D2, D3 = date(2026, 11, 18), date(2026, 11, 19), date(2026, 11, 20)


def k(clicks=0, leads=0, sales=0, rejected=0, lead_rev="0", sale_rev="0") -> Counts:
    return Counts(clicks, leads, sales, rejected, Decimal(lead_rev), Decimal(sale_rev))


# --- parsing where the data enters -------------------------------------------------------


def test_report_row_accepts_numbers_or_numeric_strings():
    row = KtReportRow.model_validate(
        {"stream_id": "7", "offer_id": 12, "day": "2026-11-19", "clicks": "100", "leads": 2,
         "sales": "3", "rejected": 0, "lead_revenue": "1.10", "sale_revenue": 0.1})
    assert row.to_day_row() == DayRow(7, 12, D2, k(100, 2, 3, 0, "1.10", "0.1"))


@pytest.mark.parametrize("missing", [None, 0, ""])
def test_report_row_without_an_offer_maps_to_none(missing):
    row = KtReportRow.model_validate({"stream_id": 7, "offer_id": missing, "day": "2026-11-19"})
    assert row.to_day_row() == DayRow(7, None, D2, Counts())


def test_report_row_missing_measures_count_as_zero():
    row = KtReportRow.model_validate({"stream_id": 7, "offer_id": 3, "day": "2026-11-19"})
    assert row.to_day_row().counts == Counts()


# --- the client ---------------------------------------------------------------------------


async def test_client_sends_one_grouped_request_and_parses_rows():
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append({"path": request.url.path, "body": json.loads(request.content)})
        return httpx.Response(200, json={"rows": [
            {"stream_id": 7, "offer_id": "12", "day": "2026-11-19", "clicks": 5, "leads": 1,
             "sales": 0, "rejected": 0, "lead_revenue": "2.5", "sale_revenue": 0}], "total": 1})

    kt = KeitaroClient("https://tracker.example", "k" * 32, transport=httpx.MockTransport(handler))
    rows = await kt.report(42, D1, D3, "Europe/Moscow")
    await kt.aclose()

    assert rows == [DayRow(7, 12, D2, k(5, 1, lead_rev="2.5"))]
    assert seen == [{"path": "/admin_api/v1/report/build", "body": {
        "range": {"from": "2026-11-18", "to": "2026-11-20", "timezone": "Europe/Moscow"},
        "dimensions": ["stream_id", "offer_id", "day"],
        "measures": ["clicks", "leads", "sales", "rejected", "lead_revenue", "sale_revenue"],
        "filters": [{"name": "campaign_id", "operator": "EQUALS", "expression": 42}],
    }}]


async def test_client_report_error_is_a_keitaro_error():
    fake = FakeKeitaro()
    fake.fail_next("POST", "/report/build", 403, "Access denied")
    kt = KeitaroClient("https://tracker.example", "k" * 32, transport=fake.transport)
    with pytest.raises(KeitaroError) as err:
        await kt.report(1, D1, D3, "UTC")
    await kt.aclose()
    assert err.value.status == 403


# --- the fake's /report/build -------------------------------------------------------------


def build(fake: FakeKeitaro, **body) -> httpx.Response:
    return fake.handle(httpx.Request("POST", f"{API}/report/build", json=body))


@pytest.fixture
def fake() -> FakeKeitaro:
    f = FakeKeitaro()
    f.record(1, 10, 100, D1, k(10, 1, 1, 0, "2", "3"))
    f.record(1, 10, 100, D2, k(20, 0, 2, 1, "0", "6"))
    f.record(1, 10, None, D2, k(5))
    f.record(1, 11, 200, D3, k(7, 1))
    f.record(2, 20, 100, D2, k(1000, 50, 50, 0, "99", "99"))
    return f


MEASURES = ["clicks", "leads", "sales", "rejected", "lead_revenue", "sale_revenue"]
CAMPAIGN_1 = [{"name": "campaign_id", "operator": "EQUALS", "expression": 1}]


def test_fake_groups_by_the_requested_dimensions(fake):
    rows = build(fake, range={"from": "2026-11-18", "to": "2026-11-20", "timezone": "UTC"},
                 dimensions=["stream_id", "offer_id", "day"], measures=MEASURES,
                 filters=CAMPAIGN_1).json()
    assert rows["total"] == 4
    assert {(r["stream_id"], r["offer_id"], r["day"], r["clicks"]) for r in rows["rows"]} == {
        (10, 100, "2026-11-18", 10), (10, 100, "2026-11-19", 20), (10, None, "2026-11-19", 5),
        (11, 200, "2026-11-20", 7)}


def test_fake_sums_measures_over_dropped_dimensions(fake):
    rows = build(fake, range={"from": "2026-11-18", "to": "2026-11-20", "timezone": "UTC"},
                 dimensions=["offer_id"], measures=MEASURES, filters=CAMPAIGN_1).json()["rows"]
    by_offer = {r["offer_id"]: r for r in rows}
    assert by_offer[100] == {"offer_id": 100, "clicks": 30, "leads": 1, "sales": 3,
                             "rejected": 1, "lead_revenue": "2", "sale_revenue": "9"}


def test_fake_without_dimensions_returns_one_totals_row(fake):
    rows = build(fake, range={"from": "2026-11-19", "to": "2026-11-19", "timezone": "UTC"},
                 dimensions=[], measures=["clicks", "sales"], filters=CAMPAIGN_1).json()
    assert rows == {"rows": [{"clicks": 25, "sales": 2}], "total": 1}


def test_fake_range_is_inclusive_on_both_ends(fake):
    rows = build(fake, range={"from": "2026-11-18", "to": "2026-11-18", "timezone": "UTC"},
                 dimensions=[], measures=["clicks"], filters=CAMPAIGN_1).json()["rows"]
    assert rows == [{"clicks": 10}]


def test_fake_filters_campaigns_with_in_list(fake):
    rows = build(fake, range={"from": "2026-11-18", "to": "2026-11-20", "timezone": "UTC"},
                 dimensions=["campaign_id"], measures=["clicks"],
                 filters=[{"name": "campaign_id", "operator": "IN_LIST", "expression": [2]}]).json()
    assert rows["rows"] == [{"campaign_id": 2, "clicks": 1000}]


def test_fake_without_a_campaign_filter_reads_every_campaign(fake):
    rows = build(fake, range={"from": "2026-11-18", "to": "2026-11-20", "timezone": "UTC"},
                 dimensions=[], measures=["clicks"], filters=[]).json()["rows"]
    assert rows == [{"clicks": 1042}]


def test_fake_rejects_an_unknown_column_like_keitaro(fake):
    resp = build(fake, range={"from": "2026-11-18", "to": "2026-11-20", "timezone": "UTC"},
                 dimensions=["stream_id"], measures=["epc_confirmed_x"], filters=CAMPAIGN_1)
    assert resp.status_code == 400
    message = resp.json()["error"]
    assert message.startswith("Column 'epc_confirmed_x' is not defined.")
    assert all(name in message for name in REPORT_COLUMNS)


def test_fake_rejects_an_unknown_dimension(fake):
    resp = build(fake, range={"from": "2026-11-18", "to": "2026-11-20", "timezone": "UTC"},
                 dimensions=["clicks"], measures=["clicks"], filters=CAMPAIGN_1)
    assert resp.status_code == 400
    assert resp.json()["error"].startswith("Column 'clicks' is not defined.")


def test_record_replaces_the_day_it_states(fake):
    fake.record(1, 10, 100, D1, k(3))
    rows = build(fake, range={"from": "2026-11-18", "to": "2026-11-18", "timezone": "UTC"},
                 dimensions=[], measures=["clicks"], filters=CAMPAIGN_1).json()["rows"]
    assert rows == [{"clicks": 3}]


async def test_client_reads_the_fake_end_to_end(fake):
    kt = KeitaroClient("https://tracker.example", "k" * 32, transport=fake.transport)
    rows = await kt.report(1, D1, D2, "UTC")
    await kt.aclose()
    assert sorted(rows, key=lambda r: (r.day, r.offer_id or 0)) == [
        DayRow(10, 100, D1, k(10, 1, 1, 0, "2", "3")), DayRow(10, None, D2, k(5)),
        DayRow(10, 100, D2, k(20, 0, 2, 1, "0", "6"))]


# --- traffic in the state file ------------------------------------------------------------


def test_traffic_survives_save_and_load(tmp_path):
    state = tmp_path / "fake.json"
    fake = FakeKeitaro(state)
    fake.record(1, 10, 100, D1, k(10, 1, 2, 3, "0.05", "4.10"))
    fake.record(1, 10, None, D2, k(5))
    fake.save()
    assert FakeKeitaro.load(state).traffic == fake.traffic


def test_old_state_file_without_traffic_loads_empty(tmp_path):
    state = tmp_path / "fake.json"
    FakeKeitaro(state).save()
    data = json.loads(state.read_text())
    del data["traffic"]
    state.write_text(json.dumps(data))
    assert FakeKeitaro.load(state).traffic == {}


def test_a_report_read_does_not_rewrite_the_state_file(tmp_path):
    state = tmp_path / "fake.json"
    fake = FakeKeitaro(state)
    build(fake, range={"from": "2026-11-18", "to": "2026-11-20", "timezone": "UTC"},
          dimensions=[], measures=["clicks"], filters=CAMPAIGN_1)
    assert not state.exists()
