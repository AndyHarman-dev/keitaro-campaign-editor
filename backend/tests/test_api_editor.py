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


def test_fetch_stages_a_rebalance_when_keitaros_shares_do_not_total_100(api, fake, cid):
    flow = offer_flow(editor(api, cid))
    fake.streams[flow["stream_id"]]["offers"][0]["share"] = 60  # Keitaro allows it
    view = api.post(f"/api/campaigns/{cid}/fetch").json()
    flow = offer_flow(view)
    assert (flow["total"], flow["dirty"], flow["pending_count"]) == (100, True, 1)
    assert (flow["rows"][0]["base_share"], flow["rows"][0]["change"]) == (60, "share")
    assert view["notes"] == ["Flow 2: Keitaro's shares total 60%; rebalanced to 100%. Push to save it."]
    again = api.post(f"/api/campaigns/{cid}/fetch").json()
    assert offer_flow(again)["pending_count"] == 1
    flow = offer_flow(again)
    api.post(f"/api/campaigns/{cid}/cancel", json={"versions": {flow["stream_id"]: flow["version"]}})
    assert offer_flow(editor(api, cid))["total"] == 60  # Cancel shows Keitaro's numbers again


def test_offer_removed_in_keitaro_hands_its_share_to_the_unpinned_offers(api, fake, cid):
    for offer_id in (4242, 5555):
        fake.add_offer(offer_id, f"Offer {offer_id}")
    view = editor(api, cid)
    for offer_id in (3717, 4242, 5555):
        view = act(api, offer_flow(view), "add", offer_id)
    view = act(api, offer_flow(view), "set_share", 18813, share=30)
    view = act(api, offer_flow(view), "set_share", 3717, share=20)
    view = push_and_view(api, view)
    assert [r[1] for r in rows(offer_flow(view))] == [30, 20, 25, 25]
    fake.detach_offer(offer_flow(view)["stream_id"], 5555)
    flow = offer_flow(api.post(f"/api/campaigns/{cid}/fetch").json())
    assert rows(flow) == [(18813, 30, "active"), (3717, 20, "active"), (4242, 50, "active"),
                          (5555, 0, "removed")]
    assert flow["total"] == 100
    push(api, flow)
    assert kt_offers(fake, flow) == [(18813, 30, "active"), (3717, 20, "active"),
                                     (4242, 50, "active")]


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


def test_a_pin_only_change_is_shown_as_a_pin_change(api, cid):
    flow = offer_flow(act(api, offer_flow(editor(api, cid)), "add", 3717))
    flow = offer_flow(push_and_view(api, {"flows": [flow]}))
    flow = offer_flow(act(api, flow, "toggle_pin", 3717))
    assert (flow["dirty"], flow["pending_count"]) == (True, 1)
    assert [(r["offer_id"], r["change"], r["pinned"]) for r in flow["rows"]] == [
        (18813, None, False), (3717, "pin", True)]
    flow = offer_flow(push_and_view(api, {"flows": [flow]}))
    flow = offer_flow(act(api, flow, "toggle_pin", 3717))
    assert [(r["change"], r["pinned"]) for r in flow["rows"]][1] == ("pin", False)


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


def test_removing_the_only_offer_and_pushing_empties_the_flow(api, fake, cid):
    flow = offer_flow(act(api, offer_flow(editor(api, cid)), "remove", 18813))
    resp = push(api, flow)
    assert resp.status_code == 200, resp.text
    assert json.loads(puts(fake)[0].content) == {"offers": []}
    flow = offer_flow(resp.json())
    assert (flow["has_offers"], flow["total"], flow["dirty"]) == (True, 0, False)
    assert rows(flow) == [(18813, 0, "removed")]  # still listed, so it can be brought back
    again = api.post(f"/api/campaigns/{cid}/fetch").json()
    assert (offer_flow(again)["pending_count"], again["notes"]) == (0, [])
    flow = offer_flow(act(api, offer_flow(again), "bring_back", 18813))
    push(api, flow)
    assert kt_offers(fake, flow) == [(18813, 100, "active")]


def test_offer_removed_in_keitaro_is_kept_and_can_be_brought_back(api, fake, cid):
    flow = offer_flow(act(api, offer_flow(editor(api, cid)), "add", 3717))
    flow = offer_flow(push(api, flow).json())
    fake.detach_offer(flow["stream_id"], 3717)
    view = api.post(f"/api/campaigns/{cid}/fetch").json()
    flow = offer_flow(view)
    assert view["notes"] == [("Flow 2: Offer [3717] was removed from this flow in Keitaro. "
                             "Bring back + Push re-attaches it."),
                             "Flow 2: Keitaro's shares total 50%; rebalanced to 100%. Push to save it."]
    assert flow["rows"][1]["removed_by"] == "keitaro"
    assert flow["rows"][0]["share"] == 100
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
    # forgetting is a local base edit: Keitaro still holds 18813 at 50 %; 100 % is pending
    flow = offer_flow(resp.json())
    assert rows(flow) == [(18813, 100, "active")]
    assert (flow["rows"][0]["base_share"], flow["pending_count"]) == (50, 1)
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



def test_push_all_reports_an_invalid_flow_and_still_pushes_the_others(api, fake, cid,
                                                                     monkeypatch):
    def refuse_empty(working):
        if not any(r.active for r in working.rows):
            raise flows_service.InvalidPush("active shares must total 100 (got 0 over 0)")
        return real_plan(working)

    real_plan = flows_service.push_plan
    monkeypatch.setattr(flows_service, "push_plan", refuse_empty)  # edits can't produce one now
    _second_offer_flow(fake, cid)
    view = editor(api, cid)
    view = act(api, offer_flow(view, "Flow 2"), "add", 3717)
    view = act(api, offer_flow(view, "Flow 3"), "remove", 3717)
    versions = {str(f["stream_id"]): f["version"] for f in view["flows"]}
    resp = api.post(f"/api/campaigns/{cid}/push", json={"versions": versions})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [n for n in body["notes"] if n.startswith("Flow 3: ")] != []
    assert offer_flow(body, "Flow 2")["dirty"] is False
    assert offer_flow(body, "Flow 3")["dirty"] is True


def test_push_all_reports_a_keitaro_error_and_still_pushes_the_others(api, fake, cid):
    _second_offer_flow(fake, cid)
    view = editor(api, cid)
    view = act(api, offer_flow(view, "Flow 2"), "add", 3717)
    view = act(api, offer_flow(view, "Flow 3"), "add", 18813)
    fake.fail_next("PUT", f"/streams/{offer_flow(view, 'Flow 3')['stream_id']}", 500, "Boom")
    versions = {str(f["stream_id"]): f["version"] for f in view["flows"]}
    body = api.post(f"/api/campaigns/{cid}/push", json={"versions": versions}).json()
    assert "Flow 3: Keitaro answered 500: Boom" in body["notes"]
    assert offer_flow(body, "Flow 2")["dirty"] is False
    assert offer_flow(body, "Flow 3")["dirty"] is True


def test_failed_reread_after_a_successful_put_keeps_what_was_sent(api, fake, cid, monkeypatch):
    flow = offer_flow(act(api, offer_flow(editor(api, cid)), "add", 3717))
    real = fake._put_stream

    def put_then_break_reads(request, match):
        fake.fail_next("GET", f"/streams/{flow['stream_id']}", 504, "Gateway timeout")
        return real(request, match)

    fake._routes = [(m, p, put_then_break_reads if h == real else h) for m, p, h in fake._routes]
    resp = push(api, flow)
    assert resp.status_code == 200, resp.text
    after = offer_flow(resp.json())
    assert (after["dirty"], rows(after)) == (False, [(18813, 50, "active"), (3717, 50, "active")])
    after = offer_flow(act(api, after, "set_share", 3717, share=70))
    assert push(api, after).status_code == 200
    assert kt_offers(fake, after) == [(18813, 30, "active"), (3717, 70, "active")]


def test_flow_deleted_in_keitaro_leaves_the_editor_on_fetch(api, fake, cid):
    _second_offer_flow(fake, cid)
    view = editor(api, cid)
    act(api, offer_flow(view, "Flow 3"), "add", 18813)
    del fake.streams[offer_flow(view, "Flow 3")["stream_id"]]
    body = api.post(f"/api/campaigns/{cid}/fetch").json()
    assert [f["name"] for f in body["flows"]] == ["Flow 1", "Flow 2"]
    assert body["notes"] == ["Flow 3 was deleted in Keitaro; its pending changes were dropped."]


def test_flow_deleted_in_keitaro_without_edits_leaves_quietly(api, fake, cid):
    _second_offer_flow(fake, cid)
    view = editor(api, cid)
    del fake.streams[offer_flow(view, "Flow 3")["stream_id"]]
    body = api.post(f"/api/campaigns/{cid}/fetch").json()
    assert body["notes"] == ["Flow 3 was deleted in Keitaro."]


def test_fetch_drops_pending_ops_that_no_longer_do_anything(api, fake, cid):
    view = act(api, offer_flow(editor(api, cid)), "add", 3717)
    view = push_and_view(api, view)
    view = act(api, offer_flow(view), "remove", 3717)
    view = act(api, offer_flow(view), "set_share", 18813, share=100)
    fake.detach_offer(offer_flow(view)["stream_id"], 3717)
    first = api.post(f"/api/campaigns/{cid}/fetch").json()
    assert any("3717" in n for n in first["notes"])
    second = api.post(f"/api/campaigns/{cid}/fetch").json()
    assert second["notes"] == []


def push_and_view(api, view: dict) -> dict:
    resp = push(api, offer_flow(view))
    assert resp.status_code == 200, resp.text
    return resp.json()
