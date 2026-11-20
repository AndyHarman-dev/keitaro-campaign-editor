"""Typed async client for the Keitaro Admin API (v1).

The API key travels only in the `Api-Key` header. It is never logged and never put into an
error. Paths ending in `clean_archive` are refused before any I/O: those endpoints purge the
archive of the whole (shared) tracker.
"""

from datetime import date
from typing import Any

import httpx

from app.domain.flow import OfferLink
from app.domain.stats import DayRow
from app.keitaro.schemas import KtCampaign, KtNamed, KtOffer, KtReportRow, KtStream

REPORT_DIMENSIONS = ["stream_id", "offer_id", "day"]
REPORT_MEASURES = ["clicks", "leads", "sales", "rejected", "lead_revenue", "sale_revenue"]


class KeitaroError(Exception):
    """A failed Keitaro call. status 0 means the tracker could not be reached."""

    def __init__(self, status: int, message: str):
        super().__init__(f"Keitaro answered {status}: {message}")
        self.status = status
        self.message = message


class UnreadableReport(KeitaroError):
    """Keitaro answered 200, but the body is not the report we asked for."""

    def __init__(self, message: str):
        super().__init__(200, message)


class ForbiddenPath(Exception):
    pass


def _check_path(path: str) -> None:
    if path.rstrip("/").lower().endswith("clean_archive"):
        raise ForbiddenPath(f"{path} purges the whole tracker's archive and is never called")


def _error_message(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text
    if isinstance(body, dict) and body.get("error"):
        return str(body["error"])
    return resp.text


class KeitaroClient:
    def __init__(self, base_url: str, api_key: str, transport: httpx.AsyncBaseTransport | None = None):
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/admin_api/v1",
            headers={"Api-Key": api_key},
            timeout=20.0,
            transport=transport,
        )

    def __repr__(self) -> str:
        return f"KeitaroClient({self._http.base_url})"

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        _check_path(path)
        try:
            resp = await self._http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise KeitaroError(0, f"tracker unreachable ({type(exc).__name__})") from None
        if resp.status_code >= 400:
            raise KeitaroError(resp.status_code, _error_message(resp))
        return resp.json() if resp.content else None

    # --- campaigns ---------------------------------------------------------------------

    async def list_campaigns(self) -> list[KtCampaign]:
        return [KtCampaign.model_validate(c) for c in await self._request("GET", "/campaigns")]

    async def get_campaign(self, campaign_id: int) -> KtCampaign:
        return KtCampaign.model_validate(await self._request("GET", f"/campaigns/{campaign_id}"))

    async def create_campaign(self, *, name: str, alias: str, domain_id: int, group_id: int,
                              traffic_source_id: int) -> KtCampaign:
        body = {"name": name, "alias": alias, "domain_id": domain_id, "group_id": group_id,
                "traffic_source_id": traffic_source_id, "type": "position", "cost_type": "CPC"}
        return KtCampaign.model_validate(await self._request("POST", "/campaigns", json=body))

    async def archive_campaign(self, campaign_id: int) -> None:
        """DELETE archives in Keitaro (verified); the campaign then 404s on GET."""
        await self._request("DELETE", f"/campaigns/{campaign_id}")

    # --- flows (the API calls them streams) --------------------------------------------

    async def list_streams(self, campaign_id: int) -> list[KtStream]:
        data = await self._request("GET", f"/campaigns/{campaign_id}/streams")
        return sorted((KtStream.model_validate(s) for s in data), key=lambda s: s.position)

    async def get_stream(self, stream_id: int) -> KtStream:
        return KtStream.model_validate(await self._request("GET", f"/streams/{stream_id}"))

    async def _create_stream(self, body: dict[str, Any]) -> KtStream:
        return KtStream.model_validate(await self._request("POST", "/streams", json=body))

    async def create_redirect_stream(self, campaign_id: int, name: str, position: int,
                                     countries: list[str], url: str) -> KtStream:
        return await self._create_stream({
            "campaign_id": campaign_id, "name": name, "position": position, "type": "forced",
            "schema": "redirect", "action_type": "http", "action_payload": url,
            "filters": [{"name": "country", "mode": "accept", "payload": countries}],
        })

    async def create_offer_stream(self, campaign_id: int, name: str, position: int,
                                  offers: list[OfferLink]) -> KtStream:
        return await self._create_stream({
            "campaign_id": campaign_id, "name": name, "position": position, "type": "regular",
            "schema": "landings", "action_type": "http", "offers": _links(offers),
        })

    async def put_stream_offers(self, stream_id: int, offers: list[OfferLink]) -> KtStream:
        """Replaces the flow's WHOLE offer list (verified). Callers send every offer."""
        data = await self._request("PUT", f"/streams/{stream_id}", json={"offers": _links(offers)})
        return KtStream.model_validate(data)

    # --- offers and lookups ------------------------------------------------------------

    async def list_offers(self) -> list[KtOffer]:
        return [KtOffer.model_validate(o) for o in await self._request("GET", "/offers")]

    async def list_deleted_offer_ids(self) -> set[int]:
        return {int(o["id"]) for o in await self._request("GET", "/offers/deleted")}

    async def _named(self, path: str, **params: str) -> list[KtNamed]:
        return [KtNamed.model_validate(x) for x in await self._request("GET", path, params=params)]

    async def list_domains(self) -> list[KtNamed]:
        return await self._named("/domains")

    async def list_campaign_groups(self) -> list[KtNamed]:
        return await self._named("/groups", type="campaigns")

    async def list_traffic_sources(self) -> list[KtNamed]:
        return await self._named("/traffic_sources")

    # --- reports -----------------------------------------------------------------------

    async def report(self, campaign_id: int, since: date, until: date, tz: str) -> list[DayRow]:
        """One campaign's rows per flow, offer and day; `until` is inclusive (A2)."""
        body = {"range": {"from": since.isoformat(), "to": until.isoformat(), "timezone": tz},
                "dimensions": REPORT_DIMENSIONS, "measures": REPORT_MEASURES,
                "filters": [{"name": "campaign_id", "operator": "EQUALS",
                             "expression": campaign_id}]}
        try:
            data = await self._request("POST", "/report/build", json=body)
            return [KtReportRow.model_validate(r).to_day_row() for r in data["rows"]]
        except (ValueError, KeyError, TypeError) as exc:  # ValidationError is a ValueError
            raise UnreadableReport(type(exc).__name__) from None


def _links(offers: list[OfferLink]) -> list[dict[str, Any]]:
    return [{"offer_id": o.offer_id, "share": o.share, "state": o.state} for o in offers]
