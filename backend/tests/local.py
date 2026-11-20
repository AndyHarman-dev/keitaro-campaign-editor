"""A test client that calls the API the way the local UI does: on localhost (see app.api.guard)."""

from fastapi import FastAPI
from fastapi.testclient import TestClient


def LocalClient(app: FastAPI) -> TestClient:
    return TestClient(app, base_url="http://localhost")
