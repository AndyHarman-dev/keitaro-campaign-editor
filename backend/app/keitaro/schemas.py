"""Keitaro responses parsed once, at the boundary. Unknown fields are ignored."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.flow import OfferLink


class _Kt(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class KtNamed(_Kt):
    id: int
    name: str


class KtCampaign(_Kt):
    id: int
    name: str
    alias: str = ""
    state: str = "active"
    domain_id: int | None = None
    group_id: int | None = None
    traffic_source_id: int | None = None
    group: str | None = None  # group name, as the campaign list returns it
    domain: str | None = None  # campaign domain URL, e.g. "https://track.example/"


class KtOffer(_Kt):
    id: int
    name: str
    state: str = "active"


class KtFilter(_Kt):
    name: str
    mode: str
    payload: Any = None


class KtStreamOffer(_Kt):
    offer_id: int
    share: int
    state: str = "active"


class KtStream(_Kt):
    id: int
    campaign_id: int
    name: str = ""
    type: str
    position: int = 0
    schema_: str = Field(default="", alias="schema")
    action_type: str | None = None
    action_payload: Any = None
    action_options: dict[str, Any] | None = None
    filters: list[KtFilter] = []
    offers: list[KtStreamOffer] = []

    @property
    def links(self) -> list[OfferLink]:
        return [OfferLink(o.offer_id, o.share, o.state) for o in self.offers]

    @property
    def redirect_url(self) -> str | None:
        """Verified: the URL is in action_payload on some flows, action_options.url on others."""
        if isinstance(self.action_payload, str) and self.action_payload:
            return self.action_payload
        return (self.action_options or {}).get("url")

    @property
    def countries(self) -> list[str]:
        return next((list(f.payload) for f in self.filters if f.name == "country"), [])
