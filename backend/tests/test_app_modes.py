"""App factory: fake-Keitaro mode for local demos and e2e, and serving the built frontend."""

from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine

from app.config import Settings
from app.db.session import Base
from app.main import create_app


def _settings(tmp_path, **extra) -> Settings:
    url = f"sqlite:///{tmp_path / 'app.db'}"
    Base.metadata.create_all(create_engine(url))
    fields = {"_env_file": None, "database_url": url, "keitaro_base_url": "https://tracker.example",
              "keitaro_api_key": SecretStr("")}
    return Settings(**(fields | extra))


def test_fake_mode_serves_a_seeded_tracker_without_a_key(tmp_path):
    api = TestClient(create_app(_settings(tmp_path, keitaro_fake=True)))
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
    lookups = TestClient(create_app(settings)).get("/api/lookups").json()
    assert lookups["problems"] == []
    assert [d["name"] for d in lookups["domains"]] == ["mine.example"]


def test_fake_controls_simulate_changes_made_in_keitaro(tmp_path):
    api = TestClient(create_app(_settings(tmp_path, keitaro_fake=True)))
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
    api = TestClient(create_app(_settings(tmp_path)))
    assert api.post("/api/_fake/offers/1/archive").status_code in (404, 405)


def test_built_frontend_is_served_with_spa_fallback(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    api = TestClient(create_app(_settings(tmp_path), frontend_dist=dist))
    assert api.get("/").text == "<html>app</html>"
    assert api.get("/campaigns/123").text == "<html>app</html>"
    assert api.get("/assets/app.js").text == "console.log(1)"
    assert api.get("/api/health").json() == {"status": "ok"}
    assert api.get("/api/nope").status_code == 404


def test_no_frontend_build_means_api_only(tmp_path):
    api = TestClient(create_app(_settings(tmp_path), frontend_dist=tmp_path / "missing"))
    assert api.get("/").status_code == 404


def test_fake_controls_stay_out_of_the_api_schema(tmp_path):
    paths = TestClient(create_app(_settings(tmp_path, keitaro_fake=True))).get(
        "/openapi.json").json()["paths"]
    assert not [p for p in paths if p.startswith("/api/_fake")]
