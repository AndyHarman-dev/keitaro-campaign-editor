from app.main import app
from tests.local import LocalClient


def test_health():
    assert LocalClient(app).get("/api/health").json() == {"status": "ok"}
