"""HTTP request/response models. The TS client types are generated from these."""

import re
from datetime import datetime
from typing import Annotated, Literal

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


# --- editor ------------------------------------------------------------------------------

class RowView(BaseModel):
    offer_id: int
    name: str | None = Field(description="null when this API key cannot read the offer")
    share: int
    pinned: bool
    status: Literal["active", "removed"]
    removed_by: Literal["local", "keitaro"] | None
    archived: bool
    change: Literal["added", "removed", "restored", "share"] | None = Field(
        description="pending change against the last fetch/push")
    base_share: int | None


class FlowView(BaseModel):
    stream_id: int
    name: str
    type: str
    position: int
    summary: str
    has_offers: bool
    version: int
    dirty: bool
    pending_count: int
    rows: list[RowView]


class CampaignRef(BaseModel):
    id: int
    name: str


class EditorView(BaseModel):
    campaign: CampaignRef
    kt_url: str
    fetched_at: datetime | None
    flows: list[FlowView]
    notes: list[str]


class RemoveIn(BaseModel):
    kind: Literal["remove"]
    offer_id: int


class BringBackIn(BaseModel):
    kind: Literal["bring_back"]
    offer_id: int


class AddIn(BaseModel):
    kind: Literal["add"]
    offer_id: int


class SetShareIn(BaseModel):
    kind: Literal["set_share"]
    offer_id: int
    share: int = Field(ge=0, le=100)


class TogglePinIn(BaseModel):
    kind: Literal["toggle_pin"]
    offer_id: int


OpIn = Annotated[RemoveIn | BringBackIn | AddIn | SetShareIn | TogglePinIn,
                 Field(discriminator="kind")]


class OpRequest(BaseModel):
    version: int
    op: OpIn


class VersionIn(BaseModel):
    version: int


class ForgetIn(BaseModel):
    version: int
    offer_id: int


class VersionsIn(BaseModel):
    versions: dict[int, int] = Field(description="stream_id -> version the client saw")


class FlowProblem(BaseModel):
    kind: Literal["conflict", "stale"]
    message: str
