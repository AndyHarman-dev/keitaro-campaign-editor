"""Stats & trends (beta). The UI's only switch: it reads `status` and decides nothing else."""

from fastapi import APIRouter

from app.api.deps import Config, Keitaro, StatsCache, Today
from app.api.schemas import PeriodParam, StatsDisabled, StatsOut
from app.services.stats import campaign_stats

router = APIRouter(prefix="/api")


@router.get("/campaigns/{campaign_id}/stats")
async def stats(campaign_id: int, settings: Config, kt: Keitaro, cache: StatsCache, today: Today,
                period: PeriodParam = "7", refresh: bool = False) -> StatsOut:
    """Per flow: totals over the period and, per offer, its numbers and trend. Always 200."""
    if not settings.stats_beta:
        return StatsDisabled(status="disabled")
    return await campaign_stats(kt, settings, cache, campaign_id, period, today, refresh)
