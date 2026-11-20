"""In-process model of the Keitaro Admin API, as verified on the live tracker (vision §4).

Used by every automated test and by `KEITARO_FAKE=1` dev/e2e runs. It reproduces the
behaviour the app depends on:
- PUT /streams/{id} with `offers` replaces the whole list; without `offers` it keeps them.
- An offer that stays keeps its link id; a removed and re-added offer gets a new one.
- Shares are not validated.
- DELETE /campaigns/{id} archives: GET then answers 404 and the list leaves it out.
- Offers this key may not read answer 403 and are missing from GET /offers.
- Any clean_archive request fails the test loudly (the client must never send one).
"""

from __future__ import annotations

import itertools
import json
import re
from collections.abc import Callable
from typing import Any

import httpx

Handler = Callable[[httpx.Request, re.Match[str]], httpx.Response]


def _ok(body: Any) -> httpx.Response:
    return httpx.Response(200, json=body)


def _err(status: int, message: str) -> httpx.Response:
    return httpx.Response(status, json={"error": message})


class FakeKeitaro:
    def __init__(self) -> None:
        self.campaigns: dict[int, dict[str, Any]] = {}
        self.streams: dict[int, dict[str, Any]] = {}
        self.offers: dict[int, dict[str, Any]] = {}
        self.unreadable: set[int] = set()
        self.deleted_offers: set[int] = set()
        self.domains: list[dict[str, Any]] = []
        self.groups: list[dict[str, Any]] = []
        self.sources: list[dict[str, Any]] = []
        self.requests: list[httpx.Request] = []
        self._failures: list[tuple[str, str, int, str]] = []
        self._ids = itertools.count(1000)
        self._routes: list[tuple[str, re.Pattern[str], Handler]] = [
            ("GET", re.compile(r"/campaigns"), self._list_campaigns),
            ("POST", re.compile(r"/campaigns"), self._create_campaign),
            ("GET", re.compile(r"/campaigns/(\d+)"), self._get_campaign),
            ("DELETE", re.compile(r"/campaigns/(\d+)"), self._archive_campaign),
            ("GET", re.compile(r"/campaigns/(\d+)/streams"), self._list_streams),
            ("POST", re.compile(r"/streams"), self._create_stream),
            ("GET", re.compile(r"/streams/(\d+)"), self._get_stream),
            ("PUT", re.compile(r"/streams/(\d+)"), self._put_stream),
            ("GET", re.compile(r"/offers"), self._list_offers),
            ("GET", re.compile(r"/offers/deleted"), self._deleted_offers),
            ("GET", re.compile(r"/domains"), lambda r, m: _ok(self.domains)),
            ("GET", re.compile(r"/groups"), self._list_groups),
            ("GET", re.compile(r"/traffic_sources"), lambda r, m: _ok(self.sources)),
        ]

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    # --- test helpers ------------------------------------------------------------------

    def add_offer(self, offer_id: int, name: str, readable: bool = True,
                  preview_path: str | None = None) -> None:
        self.offers[offer_id] = {"id": offer_id, "name": name, "state": "active",
                                 "preview_path": preview_path}
        if not readable:
            self.unreadable.add(offer_id)

    def archive_offer(self, offer_id: int) -> None:
        self.deleted_offers.add(offer_id)

    def fail_next(self, method: str, path: str, status: int, message: str) -> None:
        """The next `method path` request answers `status` with Keitaro's error body."""
        self._failures.append((method, path, status, message))

    def detach_offer(self, stream_id: int, offer_id: int) -> None:
        """What a person removing the offer in Keitaro's UI does."""
        stream = self.streams[stream_id]
        stream["offers"] = [o for o in stream["offers"] if o["offer_id"] != offer_id]

    def flows_of(self, campaign_id: int) -> list[dict[str, Any]]:
        return [s for s in self.streams.values() if s["campaign_id"] == campaign_id]

    # --- dispatch ----------------------------------------------------------------------

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path.removeprefix("/admin_api/v1").rstrip("/") or "/"
        assert "clean_archive" not in path.lower(), "clean_archive must never be called"
        for i, (method, fpath, status, message) in enumerate(self._failures):
            if method == request.method and fpath == path:
                del self._failures[i]
                return _err(status, message)
        for method, pattern, handler in self._routes:
            if method == request.method and (match := pattern.fullmatch(path)):
                return handler(request, match)
        return _err(404, f"no route {request.method} {path}")

    # --- campaigns ---------------------------------------------------------------------

    def _live_campaign(self, match: re.Match[str]) -> dict[str, Any] | None:
        campaign = self.campaigns.get(int(match.group(1)))
        return campaign if campaign and campaign["state"] != "deleted" else None

    def _list_campaigns(self, request: httpx.Request, match: re.Match[str]) -> httpx.Response:
        return _ok([c for c in self.campaigns.values() if c["state"] != "deleted"])

    def _create_campaign(self, request: httpx.Request, match: re.Match[str]) -> httpx.Response:
        body = json.loads(request.content)
        if not body.get("name") or not body.get("alias"):
            return _err(400, "name and alias are required")
        campaign = {"id": next(self._ids), "state": "active", **body}
        self.campaigns[campaign["id"]] = campaign
        return _ok(campaign)

    def _get_campaign(self, request: httpx.Request, match: re.Match[str]) -> httpx.Response:
        campaign = self._live_campaign(match)
        return _ok(campaign) if campaign else _err(404, "Not found")

    def _archive_campaign(self, request: httpx.Request, match: re.Match[str]) -> httpx.Response:
        campaign = self._live_campaign(match)
        if not campaign:
            return _err(404, "Not found")
        campaign["state"] = "deleted"
        return _ok(campaign)

    def _list_streams(self, request: httpx.Request, match: re.Match[str]) -> httpx.Response:
        if not self._live_campaign(match):
            return _err(404, "Not found")
        return _ok(self.flows_of(int(match.group(1))))

    # --- streams -----------------------------------------------------------------------

    def _links(self, stream_id: int, offers: list[dict[str, Any]],
               keep: list[dict[str, Any]]) -> list[dict[str, Any]]:
        old = {o["offer_id"]: o["id"] for o in keep}
        return [{"id": old.get(o["offer_id"]) or next(self._ids), "stream_id": stream_id,
                 "offer_id": o["offer_id"], "share": o["share"],
                 "state": o.get("state", "active")} for o in offers]

    def _create_stream(self, request: httpx.Request, match: re.Match[str]) -> httpx.Response:
        body = json.loads(request.content)
        if body.get("campaign_id") not in self.campaigns:
            return _err(400, "campaign_id is invalid")
        sid = next(self._ids)
        stream = {"filters": [], "action_options": None, "action_payload": None, **body,
                  "id": sid, "state": "active", "weight": None}
        stream["offers"] = self._links(sid, body.get("offers", []), [])
        self.streams[sid] = stream
        return _ok(stream)

    def _get_stream(self, request: httpx.Request, match: re.Match[str]) -> httpx.Response:
        stream = self.streams.get(int(match.group(1)))
        return _ok(stream) if stream else _err(404, "Not found")

    def _put_stream(self, request: httpx.Request, match: re.Match[str]) -> httpx.Response:
        stream = self.streams.get(int(match.group(1)))
        if not stream:
            return _err(404, "Not found")
        body = json.loads(request.content)
        if "offers" in body:
            stream["offers"] = self._links(stream["id"], body.pop("offers"), stream["offers"])
        stream.update(body)
        return _ok(stream)

    # --- offers and lookups ------------------------------------------------------------

    def _list_offers(self, request: httpx.Request, match: re.Match[str]) -> httpx.Response:
        hidden = self.unreadable | self.deleted_offers
        return _ok([o for oid, o in self.offers.items() if oid not in hidden])

    def _deleted_offers(self, request: httpx.Request, match: re.Match[str]) -> httpx.Response:
        return _ok([self.offers.get(oid, {"id": oid, "name": ""}) for oid in self.deleted_offers])

    def _list_groups(self, request: httpx.Request, match: re.Match[str]) -> httpx.Response:
        kind = request.url.params.get("type")
        return _ok([g for g in self.groups if kind is None or g.get("type") == kind])
