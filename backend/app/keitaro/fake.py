"""In-process model of the Keitaro Admin API, as verified on the live tracker (vision §4).

Used by every automated test and by `KEITARO_FAKE=1` dev/e2e runs. It reproduces the
behaviour the app depends on:
- PUT /streams/{id} with `offers` replaces the whole list; without `offers` it keeps them.
- An offer that stays keeps its link id; a removed and re-added offer gets a new one.
- Shares are not validated.
- DELETE /campaigns/{id} archives: GET then answers 404 and the list leaves it out.
- Offers this key may not read answer 403 and are missing from GET /offers.
- Any clean_archive request fails the test loudly (the client must never send one).
- POST /report/build groups stored daily traffic by any subset of campaign, flow, offer and
  day, filters on campaign_id, and rejects an unknown column with Keitaro's 400 message.

With a `state_file`, every change is saved there and `FakeKeitaro.load` picks it up again, so a
local demo keeps its campaigns across restarts. Tests run without one, in memory.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import asdict, fields
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from app.domain.stats import Counts
from app.keitaro.traffic import OfferProfile, default_profile

Handler = Callable[[httpx.Request, re.Match[str]], httpx.Response]
TrafficKey = tuple[int, int, int | None, date]  # campaign, flow (stream), offer, day

REPORT_DIMENSIONS = ("campaign_id", "stream_id", "offer_id", "day")
REPORT_MEASURES = tuple(f.name for f in fields(Counts))
REPORT_COLUMNS = (*REPORT_DIMENSIONS, *REPORT_MEASURES)
_READS = {("POST", "/report/build")}  # reads sent as POST: they never rewrite the state file


def _ok(body: Any) -> httpx.Response:
    return httpx.Response(200, json=body)


def _err(status: int, message: str) -> httpx.Response:
    return httpx.Response(status, json={"error": message})


class FakeKeitaro:
    def __init__(self, state_file: Path | None = None) -> None:
        self.state_file = state_file
        self.campaigns: dict[int, dict[str, Any]] = {}
        self.streams: dict[int, dict[str, Any]] = {}
        self.offers: dict[int, dict[str, Any]] = {}
        self.unreadable: set[int] = set()
        self.deleted_offers: set[int] = set()
        self.domains: list[dict[str, Any]] = []
        self.groups: list[dict[str, Any]] = []
        self.sources: list[dict[str, Any]] = []
        self.traffic: dict[TrafficKey, Counts] = {}
        self.profiles: dict[int, OfferProfile] = {}  # overrides of default_profile, in memory
        self.requests: list[httpx.Request] = []
        self._failures: list[tuple[str, str, int, str]] = []
        self._next_id = 1000
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
            ("POST", re.compile(r"/report/build"), self._report),
        ]

    def _new_id(self) -> int:
        self._next_id += 1
        return self._next_id - 1

    # --- state file --------------------------------------------------------------------

    def save(self) -> None:
        """Writes the tracker to `state_file` (no-op without one); a crash mid-write keeps the old file."""
        if self.state_file is None:
            return
        state = {"next_id": self._next_id, "campaigns": list(self.campaigns.values()),
                 "streams": list(self.streams.values()), "offers": list(self.offers.values()),
                 "unreadable": sorted(self.unreadable), "deleted_offers": sorted(self.deleted_offers),
                 "domains": self.domains, "groups": self.groups, "sources": self.sources,
                 "traffic": [_traffic_row(key, counts) for key, counts in self.traffic.items()]}
        partial = self.state_file.with_suffix(".tmp")
        partial.write_text(json.dumps(state))
        os.replace(partial, self.state_file)

    @classmethod
    def load(cls, state_file: Path) -> FakeKeitaro:
        state = json.loads(state_file.read_text())
        fake = cls(state_file)
        fake._next_id = state["next_id"]
        for attr in ("campaigns", "streams", "offers"):
            setattr(fake, attr, {item["id"]: item for item in state[attr]})
        fake.unreadable = set(state["unreadable"])
        fake.deleted_offers = set(state["deleted_offers"])
        fake.domains, fake.groups, fake.sources = state["domains"], state["groups"], state["sources"]
        fake.traffic = dict(_traffic_entry(row) for row in state.get("traffic", []))
        return fake

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
        self.save()

    def fail_next(self, method: str, path: str, status: int, message: str) -> None:
        """The next `method path` request answers `status` with Keitaro's error body."""
        self._failures.append((method, path, status, message))

    def detach_offer(self, stream_id: int, offer_id: int) -> None:
        """What a person removing the offer in Keitaro's UI does."""
        stream = self.streams[stream_id]
        stream["offers"] = [o for o in stream["offers"] if o["offer_id"] != offer_id]
        self.save()

    def record(self, campaign_id: int, stream_id: int, offer_id: int | None, day: date,
               counts: Counts) -> None:
        """States one day's exact counts for a flow and offer, replacing what was there."""
        self.traffic[(campaign_id, stream_id, offer_id, day)] = counts

    def forget_day(self, campaign_id: int, stream_id: int, day: date) -> None:
        """Drops every offer's row for one flow and day, so a re-simulated day starts empty."""
        for key in [k for k in self.traffic if k[:2] == (campaign_id, stream_id) and k[3] == day]:
            del self.traffic[key]

    def profile(self, offer_id: int) -> OfferProfile:
        return self.profiles.get(offer_id) or default_profile(offer_id)

    def flows_of(self, campaign_id: int) -> list[dict[str, Any]]:
        return [s for s in self.streams.values() if s["campaign_id"] == campaign_id]

    # --- dispatch ----------------------------------------------------------------------

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path.removeprefix("/admin_api/v1").rstrip("/") or "/"
        assert "clean_archive" not in path.lower(), "clean_archive must never be called"
        failure = self._take_failure(request.method, path)
        if failure is not None:
            return failure
        for method, pattern, handler in self._routes:
            if method == request.method and (match := pattern.fullmatch(path)):
                return self._run(handler, request, match, path)
        return _err(404, f"no route {request.method} {path}")

    def _take_failure(self, method: str, path: str) -> httpx.Response | None:
        for i, (fmethod, fpath, status, message) in enumerate(self._failures):
            if (fmethod, fpath) == (method, path):
                del self._failures[i]
                return _err(status, message)
        return None

    def _run(self, handler: Handler, request: httpx.Request, match: re.Match[str],
             path: str) -> httpx.Response:
        response = handler(request, match)
        if request.method != "GET" and (request.method, path) not in _READS:
            self.save()
        return response

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
        campaign = {"id": self._new_id(), "state": "active", **body,
                    "group": self._name(self.groups, body.get("group_id")),
                    "domain": self._domain_url(body.get("domain_id"))}
        self.campaigns[campaign["id"]] = campaign
        return _ok(campaign)

    @staticmethod
    def _name(items: list[dict[str, Any]], item_id: int | None) -> str | None:
        return next((i["name"] for i in items if i["id"] == item_id), None)

    def _domain_url(self, domain_id: int | None) -> str | None:
        name = self._name(self.domains, domain_id)
        return f"https://{name}/" if name else None

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
        return [{"id": old.get(o["offer_id"]) or self._new_id(), "stream_id": stream_id,
                 "offer_id": o["offer_id"], "share": o["share"],
                 "state": o.get("state", "active")} for o in offers]

    def _create_stream(self, request: httpx.Request, match: re.Match[str]) -> httpx.Response:
        body = json.loads(request.content)
        if body.get("campaign_id") not in self.campaigns:
            return _err(400, "campaign_id is invalid")
        sid = self._new_id()
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

    # --- reports -----------------------------------------------------------------------

    def _report(self, request: httpx.Request, match: re.Match[str]) -> httpx.Response:
        body = json.loads(request.content)
        dims, measures = body.get("dimensions", []), body.get("measures", [])
        bad = ([d for d in dims if d not in REPORT_DIMENSIONS]
               + [m for m in measures if m not in REPORT_MEASURES])
        if bad:
            return _err(400, f"Column '{bad[0]}' is not defined. The report contains only: "
                             f"{', '.join(REPORT_COLUMNS)}")
        groups: dict[tuple[Any, ...], Counts] = {}
        for key, counts in self._matching(body):
            group = tuple(_dimension(key, d) for d in dims)
            groups[group] = groups.get(group, Counts()) + counts
        rows = [{**dict(zip(dims, group)), **_measures(counts, measures)}
                for group, counts in groups.items()]
        return _ok({"rows": rows, "total": len(rows)})

    def _matching(self, body: dict[str, Any]) -> list[tuple[TrafficKey, Counts]]:
        since = date.fromisoformat(body["range"]["from"])
        until = date.fromisoformat(body["range"]["to"])
        wanted = _campaign_filter(body.get("filters", []))
        return [(key, counts) for key, counts in self.traffic.items()
                if since <= key[3] <= until and (wanted is None or key[0] in wanted)]


def _campaign_filter(filters: list[dict[str, Any]]) -> set[int] | None:
    for f in filters:
        if f["name"] == "campaign_id":
            value = f["expression"]
            return set(value) if f["operator"] == "IN_LIST" else {value}
    return None


def _dimension(key: TrafficKey, name: str) -> Any:
    value = key[REPORT_DIMENSIONS.index(name)]
    return value.isoformat() if isinstance(value, date) else value


def _measures(counts: Counts, names: list[str]) -> dict[str, Any]:
    values = asdict(counts)
    return {n: str(values[n]) if isinstance(values[n], Decimal) else values[n] for n in names}


def _traffic_row(key: TrafficKey, counts: Counts) -> dict[str, Any]:
    return {**{d: _dimension(key, d) for d in REPORT_DIMENSIONS},
            **_measures(counts, list(REPORT_MEASURES))}


def _traffic_entry(row: dict[str, Any]) -> tuple[TrafficKey, Counts]:
    key = (row["campaign_id"], row["stream_id"], row["offer_id"], date.fromisoformat(row["day"]))
    counts = Counts(**{m: Decimal(row[m]) if m.endswith("revenue") else row[m]
                       for m in REPORT_MEASURES})
    return key, counts
