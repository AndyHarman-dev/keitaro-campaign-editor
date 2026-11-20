"""HTTP request/response models. The TS client types are generated from these."""

import re

from pydantic import BaseModel, Field, field_validator

_ISO2 = re.compile(r"[A-Z]{2}")


class Named(BaseModel):
    id: int
    name: str


class CampaignOut(BaseModel):
    id: int
    name: str
    alias: str
    state: str


class Defaults(BaseModel):
    domain_id: int | None
    group_id: int | None
    source_id: int | None


class LookupsOut(BaseModel):
    domains: list[Named]
    groups: list[Named]
    sources: list[Named]
    defaults: Defaults
    problems: list[str]


class OfferOut(BaseModel):
    id: int
    name: str


class CreateCampaignIn(BaseModel):
    name: str = Field(min_length=1)
    geos: list[str] = Field(min_length=1, description="ISO 3166-1 alpha-2 codes sent to google.com")
    offer_id: int
    domain_id: int | None = None
    group_id: int | None = None
    source_id: int | None = None
    idempotency_key: str = Field(min_length=8, max_length=64)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name is required")
        return value.strip()

    @field_validator("geos")
    @classmethod
    def _geos(cls, values: list[str]) -> list[str]:
        codes = [v.strip().upper() for v in values]
        bad = [c for c in codes if not _ISO2.fullmatch(c)]
        if bad:
            raise ValueError(f"use 2-letter ISO codes, e.g. AU (got {', '.join(bad) or 'blank'})")
        return list(dict.fromkeys(codes))


class CreateCampaignOut(BaseModel):
    campaign_id: int


class KeitaroFailure(BaseModel):
    message: str
    keitaro_status: int
    archived_campaign: bool = False
