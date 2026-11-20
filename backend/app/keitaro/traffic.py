"""Seeded fake traffic for the fake tracker: demos, e2e and the band's statistical checks.

For each regular flow and day the simulator:
1. splits the day's clicks by the flow's current active shares (largest remainders), with a
   `no_offer` fraction kept off every offer (vision Rule 5) and today a `today_fraction` of a day;
2. draws postbacks ~ Binomial(clicks, p) with p = cr_all × (1 + drift)^(i / 7), capped at 1,
   i counted from the oldest simulated day, then sales ~ Binomial(postbacks, approve), the rest
   rejected. These draws never depend on `lag`;
3. with lag on, relabels some postbacks of any outcome as leads (still undecided), from a
   separate seeded stream: 90 % today, 60 % yesterday, 35 % the day before, 2 % after that;
4. books money on leads and sales at the offer's payout.

Re-running with the same arguments gives the same state: it replaces the days it covers.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from app.domain.stats import Counts

if TYPE_CHECKING:
    from app.keitaro.fake import FakeKeitaro

LAG_BY_AGE = {0: 0.9, 1: 0.6, 2: 0.35}
LAG_TAIL = 0.02


@dataclass(frozen=True)
class OfferProfile:
    cr_all: float  # chance a click produces any postback
    approve: float  # share of postbacks finally confirmed
    payout: Decimal


def default_profile(offer_id: int) -> OfferProfile:
    """Stable per offer: seeded by its id."""
    rnd = random.Random(offer_id)
    return OfferProfile(cr_all=round(rnd.uniform(0.02, 0.08), 3),
                        approve=round(rnd.uniform(0.4, 0.8), 2),
                        payout=Decimal(rnd.choice([8, 10, 12, 15, 20, 25])))


def split_clicks(total: int, shares: dict[int, int]) -> dict[int, int]:
    """Largest-remainder split, so the parts always add up to `total`."""
    weight = sum(shares.values())
    quotas = {oid: total * s / weight for oid, s in shares.items()}
    parts = {oid: math.floor(q) for oid, q in quotas.items()}
    by_remainder = sorted(quotas, key=lambda oid: parts[oid] - quotas[oid])
    for oid in by_remainder[: total - sum(parts.values())]:
        parts[oid] += 1
    return parts


def _active_shares(stream: dict[str, Any]) -> dict[int, int]:
    return {o["offer_id"]: o["share"] for o in stream.get("offers", [])
            if o.get("state", "active") == "active" and o["share"] > 0}


@dataclass(frozen=True)
class _Day:
    day: date
    index: int  # 0 = the oldest simulated day
    age: int  # 0 = today


def _outcome(rnd: random.Random, clicks: int, p: float, profile: OfferProfile) -> tuple[int, int]:
    postbacks = rnd.binomialvariate(clicks, min(1.0, p))
    return postbacks, rnd.binomialvariate(postbacks, profile.approve)


def _relabel(rnd: random.Random, sales: int, rejected: int, age: int) -> tuple[int, int]:
    undecided = LAG_BY_AGE.get(age, LAG_TAIL)
    return rnd.binomialvariate(sales, undecided), rnd.binomialvariate(rejected, undecided)


def offer_day(clicks: int, profile: OfferProfile, drift: float, d: _Day, key: str,
              lag: bool) -> Counts:
    p = profile.cr_all * (1 + drift) ** (d.index / 7)
    postbacks, sales = _outcome(random.Random(f"outcome:{key}"), clicks, p, profile)
    rejected = postbacks - sales
    from_sales, from_rejected = (_relabel(random.Random(f"lag:{key}"), sales, rejected, d.age)
                                 if lag else (0, 0))
    leads, sales, rejected = from_sales + from_rejected, sales - from_sales, rejected - from_rejected
    return Counts(clicks, leads, sales, rejected, leads * profile.payout, sales * profile.payout)


def simulate(fake: FakeKeitaro, campaign_id: int, days: int, clicks_per_day: int, *, today: date,
             seed: int, lag: bool = False, drift: dict[int, float] | None = None,
             no_offer: float = 0.0, today_fraction: float = 0.5) -> None:
    """Writes `days` complete days before `today`, plus today, into `fake.traffic`."""
    drift = drift or {}
    span = [_Day(today - timedelta(days=age), days - age, age) for age in range(days, -1, -1)]
    for stream in fake.flows_of(campaign_id):
        shares = _active_shares(stream)
        if not shares:  # redirect flows carry no offers
            continue
        for d in span:
            total = round(clicks_per_day * (today_fraction if d.age == 0 else 1))
            off_offer = round(total * no_offer)
            fake.traffic.pop((campaign_id, stream["id"], None, d.day), None)
            if off_offer:
                fake.record(campaign_id, stream["id"], None, d.day, Counts(clicks=off_offer))
            for oid, clicks in split_clicks(total - off_offer, shares).items():
                key = f"{seed}:{stream['id']}:{oid}:{d.day}"
                counts = offer_day(clicks, fake.profile(oid), drift.get(oid, 0.0), d, key, lag)
                fake.record(campaign_id, stream["id"], oid, d.day, counts)
