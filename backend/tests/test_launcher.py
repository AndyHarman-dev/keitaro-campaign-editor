"""`python -m app [--stats-beta] [uvicorn args]`: the flag travels in the environment."""

import os

import pytest
import uvicorn

from app.__main__ import main


class Uvicorn:
    def __init__(self):
        self.calls: list[tuple[list[str], str | None, str | None]] = []

    def main(self, args):
        self.calls.append((args, os.environ.get("STATS_BETA"), os.environ.get("UVICORN_APP")))


@pytest.fixture
def stub(monkeypatch):
    # setenv first so monkeypatch remembers the original state and restores it afterwards,
    # even though main() writes os.environ itself.
    for name in ("STATS_BETA", "UVICORN_APP"):
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)
    fake = Uvicorn()
    monkeypatch.setattr(uvicorn, "main", fake)
    return fake


def test_stats_beta_is_set_and_the_rest_goes_to_uvicorn(stub):
    main(["--stats-beta", "--port", "9", "--host", "::1"])
    assert stub.calls == [(["--port", "9", "--host", "::1"], "1", "app.main:app")]


def test_without_the_flag_the_beta_stays_off(stub):
    main(["--reload"])
    assert stub.calls == [(["--reload"], None, "app.main:app")]


def test_an_explicit_target_is_passed_through(stub):
    main(["other.mod:app"])
    assert stub.calls[0][0] == ["other.mod:app"]


def test_help_goes_to_uvicorn(stub):
    main(["--help"])
    assert stub.calls[0][0] == ["--help"]


def test_a_prefix_of_the_flag_is_not_taken_for_it(stub):
    main(["--st"])
    assert stub.calls == [(["--st"], None, "app.main:app")]
