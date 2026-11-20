"""Pure stats & trends maths over Keitaro report rows.

No I/O. Every number is a sum first and one division last (vision Rule 1). Definitions:
.claude/vision/stats_trends.md §3 (metrics), Rule 3 (noise band), Rule 5 (flow totals),
§4 (periods and the trend window). Glossary:

- conversions: leads + sales, Keitaro's own definition; rejected postbacks are not included.
- EPC: (lead revenue + sale revenue) / clicks. CR: conversions / clicks.
- pending share: leads / (leads + sales + rejected), how much is still undecided.
- split: an offer's clicks / all of its flow's clicks, rows with no offer included.
- settled weeks: days -16..-10 (older) and -9..-3 (newer); the last two days are still moving.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Literal

Period = Literal["today", 7, 14, 30]
TREND_DAYS = 16  # the older settled week starts 16 days back
SPARK_DAYS = 14
MIN_WEEK_CLICKS = 100
ZERO = Decimal(0)


@dataclass(frozen=True)
class Counts:
    clicks: int = 0
    leads: int = 0
    sales: int = 0
    rejected: int = 0
    lead_revenue: Decimal = ZERO
    sale_revenue: Decimal = ZERO

    def __add__(self, other: Counts) -> Counts:
        return Counts(
            self.clicks + other.clicks,
            self.leads + other.leads,
            self.sales + other.sales,
            self.rejected + other.rejected,
            self.lead_revenue + other.lead_revenue,
            self.sale_revenue + other.sale_revenue,
        )

    @property
    def conversions(self) -> int:
        return self.leads + self.sales

    @property
    def revenue(self) -> Decimal:
        return self.lead_revenue + self.sale_revenue

    @property
    def postbacks(self) -> int:
        return self.leads + self.sales + self.rejected


@dataclass(frozen=True)
class DayRow:
    stream_id: int
    offer_id: int | None
    day: date
    counts: Counts


def _days(n: int) -> timedelta:
    return timedelta(days=n)


def span(period: Period, today: date) -> tuple[date, date]:
    """Today is the partial current day; N is N complete days ending yesterday."""
    if period == "today":
        return today, today
    return today - _days(period), today - _days(1)


def report_range(period: Period, today: date) -> tuple[date, date]:
    """The one report request covers the period, the trend window and today."""
    back = TREND_DAYS if period == "today" else max(period, TREND_DAYS)
    return today - _days(back), today


def _ratio(num, den: int):
    return None if den == 0 else num / den


def _total(rows: Iterable[DayRow]) -> Counts:
    return sum((r.counts for r in rows), Counts())


def _within(rows: Iterable[DayRow], first: date, last: date) -> list[DayRow]:
    return [r for r in rows if first <= r.day <= last]


@dataclass(frozen=True)
class Cell:
    """One offer, or a flow's totals, over the period."""

    counts: Counts
    epc: Decimal | None
    cr: float | None
    pending: float | None
    split: float | None  # None for flow totals

    @classmethod
    def of(cls, k: Counts, flow_clicks: int | None) -> Cell:
        split = None if flow_clicks is None else _ratio(k.clicks, flow_clicks)
        return cls(k, _ratio(k.revenue, k.clicks), _ratio(k.conversions, k.clicks),
                   _ratio(k.leads, k.postbacks), split)


class Verdict(StrEnum):
    UP = "up"
    DOWN = "down"
    NOISE = "within_noise"
    THIN = "not_enough_traffic"


def noise_band(c1: int, c2: int) -> float:
    """Two standard errors of the log-ratio of two weekly conversion counts."""
    return 2 * math.sqrt(1 / c1 + 1 / c2)


@dataclass(frozen=True)
class Trend:
    verdict: Verdict
    daily_epc: tuple[Decimal | None, ...]  # days -14..-1; None = no clicks that day
    older: Counts
    newer: Counts
    change: float | None  # relative EPC change; None exactly when THIN
    band: float | None

    def __post_init__(self) -> None:
        thin = self.verdict is Verdict.THIN
        if thin != (self.change is None) or thin != (self.band is None):
            raise ValueError("a thin trend has no change or band, and only a thin one")

    @staticmethod
    def judge(change: float, band: float) -> Verdict:
        if abs(change) < band:
            return Verdict.NOISE
        return Verdict.UP if change >= band else Verdict.DOWN


def _thin(older: Counts, newer: Counts) -> bool:
    weeks = (older, newer)
    return (any(w.clicks < MIN_WEEK_CLICKS or w.conversions == 0 for w in weeks)
            or older.revenue == 0)


def trend(rows: Iterable[DayRow], today: date) -> Trend:
    """Settled week (days -9..-3) against the week before (days -16..-10)."""
    rows = list(rows)
    older = _total(_within(rows, today - _days(16), today - _days(10)))
    newer = _total(_within(rows, today - _days(9), today - _days(3)))
    daily = tuple(_day_epc(rows, today - _days(n)) for n in range(SPARK_DAYS, 0, -1))
    if _thin(older, newer):
        return Trend(Verdict.THIN, daily, older, newer, None, None)
    change = float(_ratio(newer.revenue, newer.clicks) / _ratio(older.revenue, older.clicks)) - 1
    band = noise_band(older.conversions, newer.conversions)
    return Trend(Trend.judge(change, band), daily, older, newer, change, band)


def _day_epc(rows: list[DayRow], day: date) -> Decimal | None:
    k = _total(_within(rows, day, day))
    return _ratio(k.revenue, k.clicks)


@dataclass(frozen=True)
class OfferStats:
    cell: Cell
    trend: Trend


@dataclass(frozen=True)
class FlowStats:
    stream_id: int
    totals: Cell
    offers: dict[int, OfferStats]


def _flow(stream_id: int, rows: list[DayRow], period: Period, today: date) -> FlowStats:
    in_period = _within(rows, *span(period, today))
    totals = _total(in_period)
    by_offer: dict[int, list[DayRow]] = defaultdict(list)
    for r in rows:
        if r.offer_id is not None:
            by_offer[r.offer_id].append(r)
    offers = {}
    for oid, offer_rows in sorted(by_offer.items()):
        period_counts = _total(_within(offer_rows, *span(period, today)))
        offers[oid] = OfferStats(Cell.of(period_counts, totals.clicks), trend(offer_rows, today))
    return FlowStats(stream_id, Cell.of(totals, None), offers)


def summarize(rows: Iterable[DayRow], period: Period, today: date) -> dict[int, FlowStats]:
    """Per flow: totals over the period (Rule 5) and, per offer, its cell and trend."""
    by_flow: dict[int, list[DayRow]] = defaultdict(list)
    for r in rows:
        by_flow[r.stream_id].append(r)
    return {sid: _flow(sid, flow_rows, period, today) for sid, flow_rows in sorted(by_flow.items())}
