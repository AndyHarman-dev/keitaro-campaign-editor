"""App factory: fake-Keitaro mode for local demos and e2e, and serving the built frontend."""

from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine

from app.config import Settings
from app.db.session import Base
from app.main import create_app
from tests.local import LocalClient


def _settings(tmp_path, **extra) -> Settings:
    url = f"sqlite:///{tmp_path / 'app.db'}"
    Base.metadata.create_all(create_engine(url))
    fields = {"_env_file": None, "database_url": url, "keitaro_base_url": "https://tracker.example",
              "keitaro_api_key": SecretStr("")}
    return Settings(**(fields | extra))


def test_fake_mode_serves_a_seeded_tracker_without_a_key(tmp_path):
    api = LocalClient(create_app(_settings(tmp_path, keitaro_fake=True)))
    assert api.get("/api/keitaro/ping").json()["reachable"] is True
    lookups = api.get("/api/lookups").json()
    assert lookups["problems"] == []
    assert lookups["defaults"]["domain_id"] is not None
    names = [o["name"] for o in api.get("/api/offers").json()]
    assert "Oxys BE" in names
    demo = api.get("/api/campaigns?q=demo").json()
    assert [c["name"] for c in demo] == ["Demo campaign"]


def test_fake_mode_uses_the_env_default_names(tmp_path):
    settings = _settings(tmp_path, keitaro_fake=True, keitaro_default_domain="mine.example",
                         keitaro_default_group="Mine", keitaro_default_source="Src")
    lookups = LocalClient(create_app(settings)).get("/api/lookups").json()
    assert lookups["problems"] == []
    assert [d["name"] for d in lookups["domains"]] == ["mine.example"]


def test_fake_controls_simulate_changes_made_in_keitaro(tmp_path):
    api = LocalClient(create_app(_settings(tmp_path, keitaro_fake=True)))
    cid = api.get("/api/campaigns?q=demo").json()[0]["id"]
    flow = next(f for f in api.get(f"/api/campaigns/{cid}/editor").json()["flows"]
                if f["has_offers"])
    offer = flow["rows"][0]["offer_id"]
    assert api.post(f"/api/_fake/streams/{flow['stream_id']}/detach/{offer}").status_code == 204
    assert api.post(f"/api/_fake/offers/{offer}/archive").status_code == 204
    view = api.post(f"/api/campaigns/{cid}/fetch").json()
    row = next(f for f in view["flows"] if f["has_offers"])["rows"][0]
    assert (row["status"], row["archived"]) == ("removed", True)


def test_fake_controls_do_not_exist_against_a_real_tracker(tmp_path):
    api = LocalClient(create_app(_settings(tmp_path)))
    assert api.post("/api/_fake/offers/1/archive").status_code in (404, 405)


def test_built_frontend_is_served_with_spa_fallback(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    api = LocalClient(create_app(_settings(tmp_path), frontend_dist=dist))
    assert api.get("/").text == "<html>app</html>"
    assert api.get("/campaigns/123").text == "<html>app</html>"
    assert api.get("/assets/app.js").text == "console.log(1)"
    assert api.get("/api/health").json() == {"status": "ok"}
    assert api.get("/api/nope").status_code == 404


def test_index_html_is_never_cached_so_a_rebuild_reaches_open_tabs(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>")
    (dist / "assets" / "app-1a2b.js").write_text("console.log(1)")
    api = LocalClient(create_app(_settings(tmp_path), frontend_dist=dist))
    assert api.get("/").headers["cache-control"] == "no-cache"
    assert api.get("/campaigns/123").headers["cache-control"] == "no-cache"
    assert api.get("/index.html").headers["cache-control"] == "no-cache"
    assert "cache-control" not in api.get("/assets/app-1a2b.js").headers  # hashed: cacheable


def test_no_frontend_build_means_api_only(tmp_path):
    api = LocalClient(create_app(_settings(tmp_path), frontend_dist=tmp_path / "missing"))
    assert api.get("/").status_code == 404


def test_fake_controls_stay_out_of_the_api_schema(tmp_path):
    paths = LocalClient(create_app(_settings(tmp_path, keitaro_fake=True))).get(
        "/openapi.json").json()["paths"]
    assert not [p for p in paths if p.startswith("/api/_fake")]


def _new_campaign(api: TestClient, name: str) -> int:
    body = {"name": name, "geos": ["AU"], "offer_id": 3749, "idempotency_key": f"key-{name}"}
    response = api.post("/api/campaigns", json=body)
    assert response.status_code == 201
    return response.json()["campaign_id"]


def test_fake_state_file_keeps_the_tracker_across_restarts(tmp_path):
    settings = _settings(tmp_path, keitaro_fake=True, keitaro_fake_state=tmp_path / "fake.json")
    first = LocalClient(create_app(settings))
    kept = _new_campaign(first, "kept one")
    flow = next(f for f in first.get(f"/api/campaigns/{kept}/editor").json()["flows"]
                if f["has_offers"])
    first.post(f"/api/flows/{flow['stream_id']}/ops",
               json={"version": flow["version"], "op": {"kind": "add", "offer_id": 3717}})
    first.post(f"/api/flows/{flow['stream_id']}/push", json={"version": flow["version"] + 1})
    first.post("/api/_fake/offers/4242/archive")

    restarted = LocalClient(create_app(settings))
    names = [c["name"] for c in restarted.get("/api/campaigns").json()]
    assert sorted(names) == ["Demo campaign", "kept one"]
    view = restarted.post(f"/api/campaigns/{kept}/fetch").json()
    shares = {r["offer_id"]: r["share"] for f in view["flows"] if f["has_offers"] for r in f["rows"]}
    assert shares == {3749: 50, 3717: 50}
    assert 4242 not in [o["id"] for o in restarted.get("/api/offers").json()]
    assert _new_campaign(restarted, "after restart") > kept


def test_fake_without_a_state_file_starts_from_the_demo_data(tmp_path):
    settings = _settings(tmp_path, keitaro_fake=True)
    _new_campaign(LocalClient(create_app(settings)), "gone")
    names = [c["name"] for c in LocalClient(create_app(settings)).get("/api/campaigns").json()]
    assert names == ["Demo campaign"]
    assert not list(tmp_path.glob("*.json"))
