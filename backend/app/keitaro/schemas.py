"""Keitaro responses parsed once, at the boundary. Unknown fields are ignored."""

from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.flow import OfferLink
from app.domain.stats import Counts, DayRow


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
    preview_path: str | None = None  # e.g. "/lander/x/_preview.png" for local landers


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


class KtReportRow(_Kt):
    """One /report/build row grouped by stream, offer and day (vision §5, assumption A1).

    Lenient on purpose: numbers may arrive as strings, a row with no offer may carry null, 0
    or "". Missing measures count as zero.
    """

    stream_id: int
    offer_id: int | None = None
    day: date
    clicks: int = 0
    leads: int = 0
    sales: int = 0
    rejected: int = 0
    lead_revenue: Decimal = Decimal(0)
    sale_revenue: Decimal = Decimal(0)

    @field_validator("offer_id", mode="before")
    @classmethod
    def _no_offer(cls, value: Any) -> Any:
        return value or None

    @field_validator("lead_revenue", "sale_revenue", mode="before")
    @classmethod
    def _exact_money(cls, value: Any) -> Any:
        return str(value)  # a float 0.1 becomes Decimal("0.1"), not its binary expansion

    def to_day_row(self) -> DayRow:
        return DayRow(self.stream_id, self.offer_id, self.day,
                      Counts(self.clicks, self.leads, self.sales, self.rejected,
                             self.lead_revenue, self.sale_revenue))
