"""Campaign lookups and the create saga (plan decision 8)."""

import secrets
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import Settings
from app.db.repository import CampaignLog
from app.domain.flow import OfferLink
from app.keitaro.client import KeitaroClient, KeitaroError
from app.keitaro.schemas import KtNamed

REDIRECT_URL = "https://google.com"


class CreateFailed(Exception):
    """`campaign_id` is set when the campaign exists in Keitaro (archived or not)."""

    def __init__(self, error: KeitaroError, archived_campaign: bool = False,
                 campaign_id: int | None = None):
        super().__init__(error.message)
        self.error = error
        self.archived_campaign = archived_campaign
        self.campaign_id = campaign_id


class MissingDefault(Exception):
    pass


@dataclass(frozen=True)
class Resolved:
    id: int | None
    problem: str | None


def resolve(env_name: str, wanted: str, options: list[KtNamed]) -> Resolved:
    """Finds the .env default (a name) among what the key can see."""
    if not wanted:
        return Resolved(None, f"{env_name} is not set.")
    found = next((o.id for o in options if o.name == wanted), None)
    if found is None:
        return Resolved(None, f"{env_name} '{wanted}' was not found in Keitaro.")
    return Resolved(found, None)


@dataclass(frozen=True)
class Lookups:
    domains: list[KtNamed]
    groups: list[KtNamed]
    sources: list[KtNamed]
    domain: Resolved
    group: Resolved
    source: Resolved

    @property
    def problems(self) -> list[str]:
        return [r.problem for r in (self.domain, self.group, self.source) if r.problem]


async def load_lookups(kt: KeitaroClient, settings: Settings) -> Lookups:
    domains = await kt.list_domains()
    groups = await kt.list_campaign_groups()
    sources = await kt.list_traffic_sources()
    return Lookups(
        domains, groups, sources,
        domain=resolve("KEITARO_DEFAULT_DOMAIN", settings.keitaro_default_domain, domains),
        group=resolve("KEITARO_DEFAULT_GROUP", settings.keitaro_default_group, groups),
        source=resolve("KEITARO_DEFAULT_SOURCE", settings.keitaro_default_source, sources),
    )


def _pick(override: int | None, default: Resolved, label: str) -> int:
    if override is not None:
        return override
    if default.id is None:
        raise MissingDefault(f"Choose a {label} under Advanced: {default.problem}")
    return default.id


@dataclass(frozen=True)
class NewCampaign:
    name: str
    geos: list[str]
    offer_id: int
    idempotency_key: str
    domain_id: int | None = None
    group_id: int | None = None
    source_id: int | None = None


async def _archive(kt: KeitaroClient, campaign_id: int) -> bool:
    """Compensation for a half-made campaign. The original error matters more than this one."""
    try:
        await kt.archive_campaign(campaign_id)
    except KeitaroError:
        return False
    return True


async def create_campaign(kt: KeitaroClient, session: Session, settings: Settings,
                          new: NewCampaign) -> int:
    log = CampaignLog(session)
    if (existing := log.find(new.idempotency_key)) is not None:
        return existing
    lookups = await load_lookups(kt, settings)
    ids = {
        "domain_id": _pick(new.domain_id, lookups.domain, "domain"),
        "group_id": _pick(new.group_id, lookups.group, "group"),
        "traffic_source_id": _pick(new.source_id, lookups.source, "traffic source"),
    }
    try:
        campaign = await kt.create_campaign(name=new.name, alias=secrets.token_hex(6), **ids)
    except KeitaroError as exc:
        raise CreateFailed(exc) from exc
    try:
        await kt.create_redirect_stream(campaign.id, "Flow 1", 1, new.geos, REDIRECT_URL)
        await kt.create_offer_stream(campaign.id, "Flow 2", 2,
                                     [OfferLink(new.offer_id, 100, "active")])
    except KeitaroError as exc:
        archived = await _archive(kt, campaign.id)
        raise CreateFailed(exc, archived, campaign.id) from exc
    except Exception:
        await _archive(kt, campaign.id)
        raise
    log.record(new.idempotency_key, campaign.id)
    session.commit()
    return campaign.id
