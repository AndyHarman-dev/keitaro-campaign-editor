"""Requests must come from this machine's own UI: DNS rebinding and cross-site POSTs are refused.

The backend holds a tracker key with write access, so a web page in the same browser must not be
able to reach it through a rebound hostname or a form/fetch aimed at 127.0.0.1.
"""

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine

from app.config import Settings
from app.db.session import Base
from app.main import create_app


@pytest.fixture
def make_client(tmp_path):
    url = f"sqlite:///{tmp_path / 'app.db'}"
    Base.metadata.create_all(create_engine(url))

    def make(base_url: str = "http://localhost:8000", **extra) -> TestClient:
        settings = Settings(_env_file=None, database_url=url, keitaro_fake=True,
                            keitaro_api_key=SecretStr(""), **extra)
        return TestClient(create_app(settings), base_url=base_url)
    return make


@pytest.mark.parametrize("base", ["http://localhost:8000", "http://127.0.0.1:8000",
                                  "http://localhost:5173"])
def test_local_hosts_are_served(make_client, base):
    assert make_client(base).get("/api/health").status_code == 200


def test_a_rebound_hostname_is_refused(make_client):
    assert make_client("http://evil.example").get("/api/health").status_code == 400


def test_extra_hosts_can_be_allowed_for_lan_use(make_client):
    client = make_client("http://192.168.1.5:8000", allowed_hosts=["192.168.1.5"])
    assert client.get("/api/health").status_code == 200


def test_a_cross_site_post_is_refused(make_client):
    client = make_client()
    response = client.post("/api/campaigns/1000/fetch", headers={"Origin": "https://evil.example"})
    assert response.status_code == 403


def test_a_post_from_a_sandboxed_or_file_page_is_refused(make_client):
    client = make_client()
    assert client.post("/api/campaigns/1000/fetch", headers={"Origin": "null"}).status_code == 403


@pytest.mark.parametrize("origin", ["http://localhost:5173", "http://127.0.0.1:8000"])
def test_a_post_from_the_ui_is_allowed(make_client, origin):
    response = make_client().post("/api/campaigns/1000/fetch", headers={"Origin": origin})
    assert response.status_code == 200


def test_a_post_without_origin_is_allowed_for_curl(make_client):
    assert make_client().post("/api/campaigns/1000/fetch").status_code == 200


def test_reads_from_another_origin_are_not_blocked_by_the_guard(make_client):
    # A cross-origin GET cannot read the response without CORS, so only writes are checked.
    response = make_client().get("/api/health", headers={"Origin": "https://evil.example"})
    assert response.status_code == 200
