"""Pins the observable output of /api/keitaro/ping (parity oracle for later changes)."""

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app import main
from app.config import Settings


def _settings(url: str = "https://tracker.example", key: str = "k" * 32) -> Settings:
    return Settings(keitaro_base_url=url, keitaro_api_key=SecretStr(key), _env_file=None)


@pytest.fixture
def client(monkeypatch):
    def use(settings: Settings) -> TestClient:
        monkeypatch.setattr(main, "get_settings", lambda: settings)
        return TestClient(main.app)

    return use


def test_ping_reports_unconfigured_when_key_missing(client):
    assert client(_settings(key="")).get("/api/keitaro/ping").json() == {"configured": False}


@respx.mock
def test_ping_counts_campaigns_when_reachable(client):
    respx.get("https://tracker.example/admin_api/v1/campaigns").mock(
        return_value=httpx.Response(200, json=[{"id": 1, "name": "a"}, {"id": 2, "name": "b"}])
    )
    assert client(_settings()).get("/api/keitaro/ping").json() == {
        "configured": True, "reachable": True, "status_code": 200, "campaigns": 2,
    }


@respx.mock
def test_ping_reports_status_when_rejected(client):
    respx.get("https://tracker.example/admin_api/v1/campaigns").mock(
        return_value=httpx.Response(401, json={"error": "unauthorized"})
    )
    assert client(_settings()).get("/api/keitaro/ping").json() == {
        "configured": True, "reachable": False, "status_code": 401, "campaigns": None,
    }
