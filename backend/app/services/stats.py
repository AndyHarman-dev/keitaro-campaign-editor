"""Stats for one campaign and period: one report call, the pure domain, then the API shape.

Read-only and separate from the editor (vision V6): nothing here is stored or staged.
"""

from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal

from app.api.deps import KeyedTtlCache
from app.api.schemas import (
    CellOut,
    FlowStatsOut,
    OfferStatsOut,
    StatsOk,
    StatsUnavailable,
    TrendOut,
    WeekOut,
)
from app.config import Settings
from app.domain.stats import Cell, Counts, FlowStats, Period, Trend, report_range, summarize
from app.keitaro.client import KeitaroClient, KeitaroError, UnreadableReport

PLACES = Decimal("0.0001")


def money(value: Decimal | None) -> str | None:
    return None if value is None else str(value.quantize(PLACES, rounding=ROUND_HALF_EVEN))


def unavailable_reason(err: KeitaroError) -> str:
    if isinstance(err, UnreadableReport):
        return "Keitaro sent a report this app can't read"
    if err.status == 403:
        return "this API key may not read reports"
    if err.status == 0 or err.status >= 500:
        return "Keitaro didn't answer in time"
    return f"Keitaro answered {err.status}"


def _cell(cell: Cell) -> CellOut:
    k = cell.counts
    return CellOut(clicks=k.clicks, leads=k.leads, sales=k.sales, rejected=k.rejected,
                   conversions=k.conversions, revenue=money(k.revenue), epc=money(cell.epc),
                   cr=cell.cr, pending=cell.pending, split=cell.split)


def _week(k: Counts) -> WeekOut:
    return WeekOut(clicks=k.clicks, conversions=k.conversions,
                   epc=money(Cell.of(k, None).epc))


def _trend(t: Trend) -> TrendOut:
    return TrendOut(verdict=t.verdict.value, daily_epc=[money(e) for e in t.daily_epc],
                    older=_week(t.older), newer=_week(t.newer), change=t.change, band=t.band)


def _flow(f: FlowStats) -> FlowStatsOut:
    offers = [OfferStatsOut(offer_id=oid, cell=_cell(o.cell), trend=_trend(o.trend))
              for oid, o in f.offers.items()]
    return FlowStatsOut(stream_id=f.stream_id, totals=_cell(f.totals), offers=offers)


PERIODS: dict[str, Period] = {"today": "today", "7": 7, "14": 14, "30": 30}


async def campaign_stats(kt: KeitaroClient, settings: Settings, cache: KeyedTtlCache,
                         campaign_id: int, param: str, today: date,
                         refresh: bool) -> StatsOk | StatsUnavailable:
    key = (campaign_id, param, today)
    if refresh:  # after Fetch or Push every period of this campaign is stale, not just this one
        cache.drop(lambda k: k[0] == campaign_id)
    cached = cache.get(key)
    if cached is not None:
        return cached
    period = PERIODS[param]
    stamp = cache.stamp()
    try:
        rows = await kt.report(campaign_id, *report_range(period, today), settings.stats_timezone)
    except KeitaroError as err:
        return StatsUnavailable(status="unavailable", reason=unavailable_reason(err))
    flows = summarize(rows, period, today)
    result = StatsOk(status="ok", period=param, as_of=today, timezone=settings.stats_timezone,
                     currency=settings.stats_currency, flows=[_flow(f) for f in flows.values()])
    cache.put(key, result, stamp=stamp)  # not if a refresh landed while we waited on Keitaro
    return result
