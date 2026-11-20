"""The fake tracker's state file: written on changes only, and read back whole."""

import httpx

from app.keitaro.fake import FakeKeitaro

_API = "https://fake.invalid/admin_api/v1"


def test_a_change_is_saved_and_a_read_writes_nothing(tmp_path):
    state = tmp_path / "fake.json"
    fake = FakeKeitaro(state)
    fake.handle(httpx.Request("GET", f"{_API}/campaigns"))
    assert not state.exists()
    fake.handle(httpx.Request("POST", f"{_API}/campaigns", json={"name": "Saved", "alias": "a1"}))
    loaded = FakeKeitaro.load(state)
    assert [c["name"] for c in loaded.campaigns.values()] == ["Saved"]
    assert loaded.state_file == state
