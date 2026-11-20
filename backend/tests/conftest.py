"""Shared fixtures: the API wired to FakeKeitaro and a throwaway SQLite database."""

import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import deps
from app.config import Settings
from app.db.session import Base
from app.keitaro.client import KeitaroClient
from app.keitaro.fake import FakeKeitaro
from app.main import app
from tests.local import LocalClient


@pytest.fixture
def fake() -> FakeKeitaro:
    kt = FakeKeitaro()
    kt.domains = [{"id": 1, "name": "track.example"}, {"id": 4, "name": "other.example"}]
    kt.groups = [{"id": 2, "name": "Team", "type": "campaigns"},
                 {"id": 9, "name": "Offer group", "type": "offers"}]
    kt.sources = [{"id": 3, "name": "Source"}]
    kt.add_offer(18813, "Flexacil PE", preview_path="/lander/flex/_preview.png")
    kt.add_offer(3717, "Oxys BE")
    kt.add_offer(500, "Someone else's offer", readable=False)
    return kt


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, keitaro_base_url="https://tracker.example",
                    keitaro_api_key=SecretStr("k" * 32), keitaro_default_domain="track.example",
                    keitaro_default_group="Team", keitaro_default_source="Source",
                    stats_beta=False)


@pytest.fixture
def api(fake, settings, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)

    async def keitaro():
        client = KeitaroClient(settings.keitaro_base_url, "k" * 32, transport=fake.transport)
        try:
            yield client
        finally:
            await client.aclose()

    def session():
        with sessions() as s:
            yield s

    stats_cache = deps.KeyedTtlCache(60)  # one per test: the app object is shared
    app.dependency_overrides = {deps.get_keitaro: keitaro, deps.get_session: session,
                                deps.get_settings: lambda: settings,
                                deps.get_stats_cache: lambda: stats_cache}
    deps.offers_cache.clear()
    yield LocalClient(app)
    app.dependency_overrides = {}
