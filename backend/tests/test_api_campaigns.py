"""Campaign list, lookups, offer search and the create saga, through the HTTP API."""

import pytest

NEW = {"name": "Spring promo", "geos": ["au", "NZ"], "offer_id": 18813,
       "idempotency_key": "4f1c2a9e-0000-4000-8000-000000000001"}


def test_campaigns_are_listed_newest_first_and_searchable(api, fake):
    for name in ("Alpha", "Beta", "Gamma"):
        fake.campaigns[len(fake.campaigns) + 1] = {"id": len(fake.campaigns) + 1, "name": name,
                                                   "alias": name.lower(), "state": "active"}
    assert [c["name"] for c in api.get("/api/campaigns").json()] == ["Gamma", "Beta", "Alpha"]
    fake.campaigns[1] |= {"group": "Team", "domain": "https://track.example/"}
    alpha = api.get("/api/campaigns?q=alpha").json()[0]
    assert (alpha["group"], alpha["domain"]) == ("Team", "track.example")
    assert [c["name"] for c in api.get("/api/campaigns?q=bet").json()] == ["Beta"]
    assert [c["name"] for c in api.get("/api/campaigns?q=1").json()] == ["Alpha"]


def test_lookups_resolve_the_env_defaults_by_name(api):
    body = api.get("/api/lookups").json()
    assert body["defaults"] == {"domain_id": 1, "group_id": 2, "source_id": 3}
    assert body["problems"] == []
    assert [g["name"] for g in body["groups"]] == ["Team"]


def test_lookups_report_defaults_that_are_unset_or_unknown(api, settings):
    settings.keitaro_default_group = ""
    settings.keitaro_default_source = "Nope"
    body = api.get("/api/lookups").json()
    assert body["defaults"] == {"domain_id": 1, "group_id": None, "source_id": None}
    assert body["problems"] == ["KEITARO_DEFAULT_GROUP is not set.",
                                "KEITARO_DEFAULT_SOURCE 'Nope' was not found in Keitaro."]


def test_offer_search_lists_readable_offers_by_name_or_id(api):
    assert [o["id"] for o in api.get("/api/offers").json()] == [18813, 3717]
    assert [o["id"] for o in api.get("/api/offers?q=oxys").json()] == [3717]
    assert [o["id"] for o in api.get("/api/offers?q=188").json()] == [18813]


def test_offer_list_is_cached_briefly(api, fake):
    api.get("/api/offers")
    fake.add_offer(42, "New offer")
    assert 42 not in [o["id"] for o in api.get("/api/offers").json()]


def test_create_builds_the_campaign_and_both_flows(api, fake):
    resp = api.post("/api/campaigns", json=NEW)
    assert resp.status_code == 201
    cid = resp.json()["campaign_id"]
    campaign = fake.campaigns[cid]
    assert (campaign["name"], campaign["domain_id"], campaign["group_id"],
            campaign["traffic_source_id"], campaign["type"], campaign["cost_type"]) == (
        "Spring promo", 1, 2, 3, "position", "CPC")
    assert len(campaign["alias"]) >= 8
    forced, offers = sorted(fake.flows_of(cid), key=lambda s: s["position"])
    assert (forced["position"], offers["position"]) == (1, 2)
    assert (forced["name"], forced["type"], forced["schema"], forced["action_payload"]) == (
        "Flow 1", "forced", "redirect", "https://google.com")
    assert forced["filters"] == [{"name": "country", "mode": "accept", "payload": ["AU", "NZ"]}]
    assert (offers["name"], offers["type"], offers["schema"]) == ("Flow 2", "regular", "landings")
    assert [(o["offer_id"], o["share"]) for o in offers["offers"]] == [(18813, 100)]


def test_advanced_overrides_replace_the_defaults(api, fake):
    cid = api.post("/api/campaigns", json=NEW | {"domain_id": 4}).json()["campaign_id"]
    assert fake.campaigns[cid]["domain_id"] == 4


def test_double_submit_returns_the_same_campaign(api, fake):
    first = api.post("/api/campaigns", json=NEW).json()["campaign_id"]
    second = api.post("/api/campaigns", json=NEW)
    assert second.status_code == 201
    assert second.json()["campaign_id"] == first
    assert len(fake.campaigns) == 1


@pytest.mark.parametrize("geos", [[], ["AUS"], ["a1"], [""]])
def test_invalid_geo_is_rejected_without_calling_keitaro(api, fake, geos):
    assert api.post("/api/campaigns", json=NEW | {"geos": geos}).status_code == 422
    assert fake.requests == []


def test_blank_name_is_rejected(api, fake):
    assert api.post("/api/campaigns", json=NEW | {"name": "   "}).status_code == 422
    assert fake.requests == []


def test_failed_flow_archives_the_half_made_campaign(api, fake):
    fake.fail_next("POST", "/streams", 400, "Invalid filter")
    resp = api.post("/api/campaigns", json=NEW)
    assert resp.status_code == 502
    assert resp.json()["detail"] == {
        "message": "Invalid filter", "keitaro_status": 400, "archived_campaign": True,
        "campaign_id": 1000}
    (campaign,) = fake.campaigns.values()
    assert campaign["state"] == "deleted"


def test_failed_campaign_create_reports_that_nothing_was_created(api, fake):
    fake.fail_next("POST", "/campaigns", 400, "Alias is already taken")
    resp = api.post("/api/campaigns", json=NEW)
    assert resp.status_code == 502
    assert resp.json()["detail"] == {
        "message": "Alias is already taken", "keitaro_status": 400, "archived_campaign": False,
        "campaign_id": None}
    assert fake.campaigns == {}


def test_create_without_a_resolvable_default_asks_for_advanced(api, fake, settings):
    settings.keitaro_default_group = ""
    resp = api.post("/api/campaigns", json=NEW)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Choose a group under Advanced: KEITARO_DEFAULT_GROUP is not set."
    assert fake.campaigns == {}


def test_keitaro_errors_on_reads_surface_as_502(api, fake):
    fake.fail_next("GET", "/campaigns", 401, "Unauthorized")
    resp = api.get("/api/campaigns")
    assert resp.status_code == 502
    assert resp.json()["detail"] == {"message": "Unauthorized", "keitaro_status": 401,
                                     "archived_campaign": False, "campaign_id": None}


def test_failed_compensation_says_the_campaign_was_not_archived(api, fake):
    fake.fail_next("POST", "/streams", 400, "Invalid filter")
    fake.fail_next("DELETE", f"/campaigns/{1000}", 500, "Archive failed")
    resp = api.post("/api/campaigns", json=NEW)
    assert resp.status_code == 502
    assert resp.json()["detail"] == {
        "message": "Invalid filter", "keitaro_status": 400, "archived_campaign": False,
        "campaign_id": 1000}
    assert fake.campaigns[1000]["state"] == "active"


def test_unexpected_error_after_create_still_archives_the_campaign(api, fake, monkeypatch):
    def broken(request, match):
        raise RuntimeError("unparseable flow")

    monkeypatch.setattr(fake, "_create_stream", broken)
    fake._routes = [(m, p, broken if h.__name__ == "_create_stream" else h)
                    for m, p, h in fake._routes]
    with pytest.raises(RuntimeError):
        api.post("/api/campaigns", json=NEW)
    (campaign,) = fake.campaigns.values()
    assert campaign["state"] == "deleted"


def test_geo_error_names_the_bad_codes(api):
    detail = api.post("/api/campaigns", json=NEW | {"geos": ["AU", "AUS"]}).json()["detail"]
    assert "use 2-letter ISO codes, e.g. AU (got AUS)" in detail[0]["msg"]
    detail = api.post("/api/campaigns", json=NEW | {"geos": [" "]}).json()["detail"]
    assert "(got blank)" in detail[0]["msg"]


def test_repeated_geos_are_sent_once(api, fake):
    cid = api.post("/api/campaigns", json=NEW | {"geos": ["au", "AU", "nz"]}).json()["campaign_id"]
    forced = next(s for s in fake.flows_of(cid) if s["type"] == "forced")
    assert forced["filters"][0]["payload"] == ["AU", "NZ"]
