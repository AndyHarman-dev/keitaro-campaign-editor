from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import cached_offers, get_keitaro, get_session, get_settings
from app.api.schemas import (
    CampaignOut,
    CreateCampaignIn,
    CreateCampaignOut,
    Defaults,
    KeitaroFailureBody,
    LookupsOut,
    Named,
    OfferOut,
)
from app.config import Settings
from app.keitaro.client import KeitaroClient
from app.services.campaigns import NewCampaign, create_campaign, load_lookups

router = APIRouter(prefix="/api", responses={502: {"model": KeitaroFailureBody}})
Keitaro = Annotated[KeitaroClient, Depends(get_keitaro)]
Db = Annotated[Session, Depends(get_session)]
Config = Annotated[Settings, Depends(get_settings)]


def _matches(q: str, *fields: object) -> bool:
    needle = q.strip().lower()
    return not needle or any(needle in str(f).lower() for f in fields)


@router.get("/campaigns")
async def list_campaigns(kt: Keitaro, q: str = "") -> list[CampaignOut]:
    campaigns = sorted(await kt.list_campaigns(), key=lambda c: c.id, reverse=True)
    return [CampaignOut(id=c.id, name=c.name, alias=c.alias, state=c.state, group=c.group,
                        domain=_host(c.domain)) for c in campaigns if _matches(q, c.id, c.name)]


def _host(url: str | None) -> str | None:
    return urlsplit(url).hostname if url else None


@router.get("/lookups")
async def lookups(kt: Keitaro, settings: Config) -> LookupsOut:
    found = await load_lookups(kt, settings)

    def named(items):
        return [Named(id=i.id, name=i.name) for i in items]

    return LookupsOut(
        domains=named(found.domains), groups=named(found.groups), sources=named(found.sources),
        defaults=Defaults(domain_id=found.domain.id, group_id=found.group.id,
                          source_id=found.source.id),
        problems=found.problems,
    )


@router.get("/offers")
async def search_offers(kt: Keitaro, q: str = "") -> list[OfferOut]:
    offers = await cached_offers(kt)
    return [OfferOut(id=o.id, name=o.name) for o in offers if _matches(q, o.id, o.name)]


@router.post("/campaigns", status_code=201)
async def create(body: CreateCampaignIn, kt: Keitaro, db: Db, settings: Config) -> CreateCampaignOut:
    new = NewCampaign(**body.model_dump())
    return CreateCampaignOut(campaign_id=await create_campaign(kt, db, settings, new))
