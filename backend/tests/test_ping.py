"""Pins the observable output of /api/keitaro/ping (parity oracle for later changes)."""

import httpx
import respx
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import Settings
from app.main import create_app
from tests.local import LocalClient


def _api(tmp_path, key: str = "k" * 32) -> TestClient:
    settings = Settings(_env_file=None, keitaro_base_url="https://tracker.example",
                        keitaro_api_key=SecretStr(key),
                        database_url=f"sqlite:///{tmp_path / 'app.db'}")
    return LocalClient(create_app(settings, frontend_dist=tmp_path / "none"))


def test_ping_reports_unconfigured_when_key_missing(tmp_path):
    assert _api(tmp_path, key="").get("/api/keitaro/ping").json() == {"configured": False}


@respx.mock
def test_ping_counts_campaigns_when_reachable(tmp_path):
    respx.get("https://tracker.example/admin_api/v1/campaigns").mock(
        return_value=httpx.Response(200, json=[{"id": 1, "name": "a"}, {"id": 2, "name": "b"}])
    )
    assert _api(tmp_path).get("/api/keitaro/ping").json() == {
        "configured": True, "reachable": True, "status_code": 200, "campaigns": 2,
    }


@respx.mock
def test_ping_reports_status_when_rejected(tmp_path):
    respx.get("https://tracker.example/admin_api/v1/campaigns").mock(
        return_value=httpx.Response(401, json={"error": "unauthorized"})
    )
    assert _api(tmp_path).get("/api/keitaro/ping").json() == {
        "configured": True, "reachable": False, "status_code": 401, "campaigns": None,
    }
