"""Editor: fetch, staged ops, push, cancel, through the HTTP API against FakeKeitaro."""

import json

import httpx
import pytest

import app.services.flows as flows_service

NEW = {"name": "Spring promo", "geos": ["AU", "NZ"], "offer_id": 18813,
       "idempotency_key": "4f1c2a9e-0000-4000-8000-000000000001"}


@pytest.fixture
def cid(api) -> int:
    return api.post("/api/campaigns", json=NEW).json()["campaign_id"]


def editor(api, cid: int) -> dict:
    resp = api.get(f"/api/campaigns/{cid}/editor")
    assert resp.status_code == 200, resp.text
    return resp.json()


def offer_flow(view: dict, name: str = "Flow 2") -> dict:
    return next(f for f in view["flows"] if f["name"] == name)


def rows(flow: dict) -> list[tuple]:
    return [(r["offer_id"], r["share"], r["status"]) for r in flow["rows"]]


def op(api, flow: dict, kind: str, offer_id: int, **extra) -> httpx.Response:
    body = {"version": flow["version"], "op": {"kind": kind, "offer_id": offer_id, **extra}}
    return api.post(f"/api/flows/{flow['stream_id']}/ops", json=body)


def act(api, flow: dict, kind: str, offer_id: int, **extra) -> dict:
    resp = op(api, flow, kind, offer_id, **extra)
    assert resp.status_code == 200, resp.text
    return resp.json()


def push(api, flow: dict) -> httpx.Response:
    return api.post(f"/api/flows/{flow['stream_id']}/push", json={"version": flow["version"]})


def puts(fake) -> list[httpx.Request]:
    return [r for r in fake.requests if r.method == "PUT"]


def kt_offers(fake, flow: dict) -> list[tuple]:
    return [(o["offer_id"], o["share"], o["state"]) for o in
            fake.streams[flow["stream_id"]]["offers"]]


# --- open and fetch ------------------------------------------------------------------------


def test_first_open_fetches_both_flows(api, cid):
    view = editor(api, cid)
    assert view["campaign"]["name"] == "Spring promo"
    assert view["kt_url"] == f"https://tracker.example/admin/#!/campaigns/{cid}"
    forced, offers = view["flows"]
    assert (forced["name"], forced["has_offers"], forced["summary"]) == (
        "Flow 1", False, "forced · country in AU, NZ → https://google.com")
    assert offers["has_offers"] is True
    assert offers["summary"] == "regular · position 2"
    assert offers["rows"] == [{
        "offer_id": 18813, "name": "Flexacil PE", "share": 100, "pinned": False,
        "status": "active", "removed_by": None, "archived": False, "change": None,
        "base_share": 100, "preview_url": "https://tracker.example/lander/flex/_preview.png",
    }]
    assert offers["total"] == 100
    assert (offers["dirty"], offers["pending_count"]) == (False, 0)


def test_unreadable_offer_is_shown_by_id_only(api, fake, cid):
    flow = offer_flow(editor(api, cid))
    fake.streams[flow["stream_id"]]["offers"].append(
        {"id": 1, "offer_id": 500, "share": 0, "state": "active"})
    view = api.post(f"/api/campaigns/{cid}/fetch").json()
    row = offer_flow(view)["rows"][1]
    assert (row["name"], row["preview_url"]) == (None, None)


def test_flow_total_is_the_sum_of_active_shares(api, fake, cid):
    flow = offer_flow(editor(api, cid))
    fake.streams[flow["stream_id"]]["offers"][0]["share"] = 60  # Keitaro allows it
    view = api.post(f"/api/campaigns/{cid}/fetch").json()
    assert offer_flow(view)["total"] == 60


def test_unknown_campaign_reports_keitaros_404(api):
    resp = api.get("/api/campaigns/999999/editor")
    assert resp.status_code == 502
    assert resp.json()["detail"]["keitaro_status"] == 404


# --- staged ops ----------------------------------------------------------------------------


def test_ops_are_staged_locally_and_nothing_is_sent(api, fake, cid):
    flow = offer_flow(editor(api, cid))
    view = act(api, flow, "add", 3717)
    flow = offer_flow(view)
    assert rows(flow) == [(18813, 50, "active"), (3717, 50, "active")]
    assert [r["change"] for r in flow["rows"]] == ["share", "added"]
    assert (flow["dirty"], flow["pending_count"]) == (True, 2)
    assert puts(fake) == []
    # survives a reload
    assert rows(offer_flow(editor(api, cid))) == rows(flow)


def test_share_edit_pins_and_reports_auto_unpin(api, cid):
    flow = offer_flow(act(api, offer_flow(editor(api, cid)), "add", 3717))
    flow = offer_flow(act(api, flow, "set_share", 3717, share=70))
    assert rows(flow) == [(18813, 30, "active"), (3717, 70, "active")]
    assert [r["pinned"] for r in flow["rows"]] == [False, True]
    view = act(api, flow, "set_share", 18813, share=40)
    assert view["notes"] == ["Flow 2: Auto-unpinned [3717]: the pinned shares did not fit in 100%."]


def test_op_that_changes_nothing_is_not_recorded(api, cid):
    flow = offer_flow(editor(api, cid))
    view = act(api, flow, "add", 18813)
    assert view["notes"] == ["Flow 2: Offer [18813] is already in this flow."]
    assert offer_flow(view)["dirty"] is False
    assert offer_flow(view)["version"] == flow["version"]


def test_ops_that_cancel_out_leave_the_flow_clean(api, cid):
    flow = offer_flow(act(api, offer_flow(editor(api, cid)), "add", 3717))
    flow = offer_flow(push(api, flow).json())
    flow = offer_flow(act(api, flow, "remove", 3717))
    flow = offer_flow(act(api, flow, "bring_back", 3717))
    assert (flow["dirty"], flow["pending_count"]) == (False, 0)
    assert rows(flow) == [(18813, 50, "active"), (3717, 50, "active")]


@pytest.mark.parametrize("bad", [{"kind": "set_share", "offer_id": 1},
                                 {"kind": "set_share", "offer_id": 1, "share": 101},
                                 {"kind": "explode", "offer_id": 1}])
def test_malformed_ops_are_rejected(api, cid, bad):
    flow = offer_flow(editor(api, cid))
    resp = api.post(f"/api/flows/{flow['stream_id']}/ops", json={"version": flow["version"],
                                                                 "op": bad})
    assert resp.status_code == 422


def test_stale_version_is_refused(api, cid):
    flow = offer_flow(editor(api, cid))
    act(api, flow, "add", 3717)
    resp = op(api, flow, "remove", 18813)  # same old version: another tab
    assert resp.status_code == 409
    assert resp.json()["detail"]["kind"] == "stale"


def test_unknown_flow_is_404(api):
    resp = api.post("/api/flows/424242/ops", json={"version": 1,
                                                   "op": {"kind": "remove", "offer_id": 1}})
    assert resp.status_code == 404


def test_cancel_drops_every_pending_change(api, fake, cid):
    flow = offer_flow(act(api, offer_flow(editor(api, cid)), "add", 3717))
    resp = api.post(f"/api/flows/{flow['stream_id']}/cancel", json={"version": flow["version"]})
    flow = offer_flow(resp.json())
    assert rows(flow) == [(18813, 100, "active")]
    assert flow["dirty"] is False
    assert puts(fake) == []


# --- push ----------------------------------------------------------------------------------


def test_push_writes_the_working_list_and_comes_back_clean(api, fake, cid):
    flow = offer_flow(act(api, offer_flow(editor(api, cid)), "add", 3717))
    resp = push(api, flow)
    assert resp.status_code == 200, resp.text
    flow = offer_flow(resp.json())
    assert kt_offers(fake, flow) == [(18813, 50, "active"), (3717, 50, "active")]
    assert (flow["dirty"], [r["change"] for r in flow["rows"]]) == (False, [None, None])
    assert json.loads(puts(fake)[-1].content) == {"offers": [
        {"offer_id": 18813, "share": 50, "state": "active"},
        {"offer_id": 3717, "share": 50, "state": "active"}]}


def test_push_keeps_an_offer_the_key_cannot_read(api, fake, cid):
    flow = offer_flow(editor(api, cid))
    fake.streams[flow["stream_id"]]["offers"] = [
        {"id": 1, "offer_id": 18813, "share": 50, "state": "active"},
        {"id": 2, "offer_id": 500, "share": 50, "state": "disabled"}]
    flow = offer_flow(api.post(f"/api/campaigns/{cid}/fetch").json())
    flow = offer_flow(act(api, flow, "add", 3717))
    assert push(api, flow).status_code == 200
    assert kt_offers(fake, flow) == [(18813, 34, "active"), (500, 33, "disabled"),
                                     (3717, 33, "active")]


def test_removed_rows_stay_listed_after_push(api, fake, cid):
    flow = offer_flow(act(api, offer_flow(editor(api, cid)), "add", 3717))
    flow = offer_flow(push(api, flow).json())
    flow = offer_flow(act(api, flow, "remove", 3717))
    flow = offer_flow(push(api, flow).json())
    assert rows(flow) == [(18813, 100, "active"), (3717, 0, "removed")]
    assert flow["rows"][1]["removed_by"] == "local"
    assert kt_offers(fake, flow) == [(18813, 100, "active")]


def test_push_of_a_clean_flow_sends_nothing(api, fake, cid):
    flow = offer_flow(editor(api, cid))
    assert push(api, flow).status_code == 200
    assert puts(fake) == []


def test_push_of_a_flow_with_every_offer_removed_is_refused(api, fake, cid):
    flow = offer_flow(act(api, offer_flow(editor(api, cid)), "remove", 18813))
    resp = push(api, flow)
    assert resp.status_code == 422
    assert puts(fake) == []


def test_offer_removed_in_keitaro_is_kept_and_can_be_brought_back(api, fake, cid):
    flow = offer_flow(act(api, offer_flow(editor(api, cid)), "add", 3717))
    flow = offer_flow(push(api, flow).json())
    fake.detach_offer(flow["stream_id"], 3717)
    view = api.post(f"/api/campaigns/{cid}/fetch").json()
    flow = offer_flow(view)
    assert view["notes"] == [("Flow 2: Offer [3717] was removed from this flow in Keitaro. "
                             "Bring back + Push re-attaches it.")]
    assert flow["rows"][1]["removed_by"] == "keitaro"
    flow = offer_flow(act(api, flow, "bring_back", 3717))
    assert flow["rows"][1]["change"] == "restored"
    push(api, flow)
    assert kt_offers(fake, flow) == [(18813, 50, "active"), (3717, 50, "active")]


def test_push_is_blocked_when_keitaro_changed_since_fetch(api, fake, cid):
    flow = offer_flow(act(api, offer_flow(editor(api, cid)), "add", 3717))
    fake.streams[flow["stream_id"]]["offers"].append(
        {"id": 9, "offer_id": 500, "share": 0, "state": "active"})
    resp = push(api, flow)
    assert resp.status_code == 409
    assert resp.json()["detail"] == {
        "kind": "conflict", "message": "Flow 2 was changed in Keitaro since your last fetch."}
    assert puts(fake) == []
    # fetch merges Keitaro's change; the pending add stays on top; push then succeeds
    flow = offer_flow(api.post(f"/api/campaigns/{cid}/fetch").json())
    assert [r["offer_id"] for r in flow["rows"]] == [18813, 500, 3717]
    assert push(api, flow).status_code == 200
    assert kt_offers(fake, flow) == [(18813, 34, "active"), (500, 33, "active"),
                                     (3717, 33, "active")]


def test_crash_between_put_and_commit_recovers_through_fetch(api, fake, cid, monkeypatch):
    flow = offer_flow(act(api, offer_flow(editor(api, cid)), "add", 3717))
    real_save = flows_service.FlowRepository.save

    def crash(self, stored):
        if stored.pending == []:
            raise RuntimeError("power cut")
        return real_save(self, stored)

    monkeypatch.setattr(flows_service.FlowRepository, "save", crash)
    with pytest.raises(RuntimeError):
        push(api, flow)
    monkeypatch.setattr(flows_service.FlowRepository, "save", real_save)
    assert kt_offers(fake, flow) == [(18813, 50, "active"), (3717, 50, "active")]

    assert push(api, offer_flow(editor(api, cid))).status_code == 409
    flow = offer_flow(api.post(f"/api/campaigns/{cid}/fetch").json())
    assert flow["dirty"] is False
    assert rows(flow) == [(18813, 50, "active"), (3717, 50, "active")]


# --- archived offers -------------------------------------------------------------------------


def test_archived_offer_is_flagged_and_forget_drops_it_locally(api, fake, cid):
    flow = offer_flow(act(api, offer_flow(editor(api, cid)), "add", 3717))
    flow = offer_flow(push(api, flow).json())
    fake.detach_offer(flow["stream_id"], 3717)
    fake.archive_offer(3717)
    flow = offer_flow(api.post(f"/api/campaigns/{cid}/fetch").json())
    assert flow["rows"][1]["archived"] is True
    sent = len(fake.requests)
    resp = api.post(f"/api/flows/{flow['stream_id']}/forget",
                    json={"version": flow["version"], "offer_id": 3717})
    assert resp.status_code == 200
    # forgetting is a local base edit: Keitaro still holds 18813 at 50 %, and that is shown
    assert rows(offer_flow(resp.json())) == [(18813, 50, "active")]
    assert [r for r in fake.requests[sent:] if r.method != "GET"] == []  # nothing written


def test_forget_refuses_rows_that_are_not_archived(api, cid):
    flow = offer_flow(editor(api, cid))
    resp = api.post(f"/api/flows/{flow['stream_id']}/forget",
                    json={"version": flow["version"], "offer_id": 18813})
    assert resp.status_code == 422


# --- push all / cancel all -------------------------------------------------------------------


def _second_offer_flow(fake, cid: int) -> None:
    fake.handle(httpx.Request("POST", "https://tracker.example/admin_api/v1/streams", json={
        "campaign_id": cid, "name": "Flow 3", "position": 3, "type": "regular",
        "schema": "landings", "action_type": "http",
        "offers": [{"offer_id": 3717, "share": 100, "state": "active"}]}))


def test_push_all_pushes_each_flow_and_reports_conflicts(api, fake, cid):
    _second_offer_flow(fake, cid)
    view = editor(api, cid)
    view = act(api, offer_flow(view, "Flow 2"), "add", 3717)
    view = act(api, offer_flow(view, "Flow 3"), "add", 18813)
    fake.streams[offer_flow(view, "Flow 3")["stream_id"]]["offers"][0]["share"] = 90
    versions = {str(f["stream_id"]): f["version"] for f in view["flows"]}
    resp = api.post(f"/api/campaigns/{cid}/push", json={"versions": versions})
    assert resp.status_code == 200
    body = resp.json()
    assert body["notes"] == ["Flow 3 was changed in Keitaro since your last fetch."]
    assert offer_flow(body, "Flow 2")["dirty"] is False
    assert offer_flow(body, "Flow 3")["dirty"] is True
    assert kt_offers(fake, offer_flow(body, "Flow 2")) == [(18813, 50, "active"),
                                                           (3717, 50, "active")]


def test_cancel_all_cleans_every_flow(api, fake, cid):
    _second_offer_flow(fake, cid)
    view = editor(api, cid)
    view = act(api, offer_flow(view, "Flow 2"), "add", 3717)
    view = act(api, offer_flow(view, "Flow 3"), "add", 18813)
    versions = {str(f["stream_id"]): f["version"] for f in view["flows"]}
    body = api.post(f"/api/campaigns/{cid}/cancel", json={"versions": versions}).json()
    assert not any(f["dirty"] for f in body["flows"])


def test_push_all_refuses_stale_versions(api, cid):
    view = editor(api, cid)
    flow = offer_flow(view)
    act(api, flow, "add", 3717)
    resp = api.post(f"/api/campaigns/{cid}/push",
                    json={"versions": {str(flow["stream_id"]): flow["version"]}})
    assert resp.status_code == 409


def test_push_reports_when_keitaro_stores_something_else(api, fake, cid, monkeypatch):
    flow = offer_flow(act(api, offer_flow(editor(api, cid)), "add", 3717))
    real = fake._links

    def normalise(stream_id, offers, keep):
        return [link | {"state": "paused"} for link in real(stream_id, offers, keep)]

    monkeypatch.setattr(fake, "_links", normalise)
    body = push(api, flow).json()
    assert body["notes"] == [("Flow 2: Keitaro stored a different offer list than was sent; "
                             "showing what Keitaro has.")]
    assert offer_flow(body)["dirty"] is False
