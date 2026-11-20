"""Flow storage: lossless round trips, optimistic versioning, and the Alembic schema."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app.db.codec import ops_from_json, ops_to_json, state_from_json, state_to_json
from app.db.repository import CampaignLog, FlowRepository, StaleVersion, StoredFlow
from app.db.session import Base
from app.domain.flow import (
    Add,
    BringBack,
    FlowState,
    OfferRow,
    Pin,
    Remove,
    RemovedBy,
    RowStatus,
    SetShare,
    TogglePin,
)

BACKEND = Path(__file__).resolve().parents[1]

STATE = FlowState(
    rows=(
        OfferRow(offer_id=1, status=RowStatus.ACTIVE, share=60, kt_state="disabled",
                 pin=Pin(60, 2)),
        OfferRow(offer_id=2, status=RowStatus.ACTIVE, share=40),
        OfferRow(offer_id=3, status=RowStatus.REMOVED, share=0, removed_by=RemovedBy.LOCAL,
                 pin=Pin(25, 1)),
        OfferRow(offer_id=4, status=RowStatus.REMOVED, share=0, removed_by=RemovedBy.KEITARO,
                 archived=True),
    ),
    next_pin_seq=3,
)
OPS = [Remove(offer_id=1), BringBack(offer_id=1), Add(offer_id=9), SetShare(offer_id=2, share=30),
       TogglePin(offer_id=2)]


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def stored(**changes) -> StoredFlow:
    fields = {"stream_id": 11, "campaign_id": 5, "name": "Flow 2", "type": "regular", "position": 2,
                  "summary": "", "base": STATE, "pending": OPS, "signature": [[1, 60, "disabled"]],
                  "fetched_at": datetime(2026, 11, 20, 12, 0, tzinfo=UTC), "version": 0}
    return StoredFlow(**(fields | changes))


def test_state_survives_a_json_round_trip():
    assert state_from_json(state_to_json(STATE)) == STATE


def test_ops_survive_a_json_round_trip():
    assert ops_from_json(ops_to_json(OPS)) == OPS


def test_unknown_op_kind_is_rejected():
    with pytest.raises(ValueError):
        ops_from_json([{"kind": "explode", "offer_id": 1}])


def test_new_flow_is_stored_and_read_back(session_factory):
    with session_factory() as s:
        saved = FlowRepository(s).save(stored())
        s.commit()
    assert saved.version == 1
    with session_factory() as s:
        assert FlowRepository(s).get(11) == stored(version=1)


def test_save_bumps_the_version(session_factory):
    with session_factory() as s:
        repo = FlowRepository(s)
        first = repo.save(stored())
        second = repo.save(stored(name="Renamed", version=first.version))
        s.commit()
    assert second.version == 2
    with session_factory() as s:
        assert FlowRepository(s).get(11).name == "Renamed"


def test_saving_a_stale_version_is_refused(session_factory):
    with session_factory() as s:
        repo = FlowRepository(s)
        repo.save(stored())
        repo.save(stored(version=1))
        with pytest.raises(StaleVersion):
            repo.save(stored(version=1))


def test_inserting_an_existing_flow_as_new_is_refused(session_factory):
    with session_factory() as s:
        repo = FlowRepository(s)
        repo.save(stored())
        with pytest.raises(StaleVersion):
            repo.save(stored(version=0))


def test_flows_of_a_campaign_come_in_position_order(session_factory):
    with session_factory() as s:
        repo = FlowRepository(s)
        repo.save(stored(stream_id=21, position=2))
        repo.save(stored(stream_id=20, position=1))
        repo.save(stored(stream_id=30, campaign_id=6))
        s.commit()
        assert [f.stream_id for f in repo.for_campaign(5)] == [20, 21]


def test_missing_flow_reads_as_none(session_factory):
    with session_factory() as s:
        assert FlowRepository(s).get(404) is None


def test_campaign_log_remembers_idempotency_keys(session_factory):
    with session_factory() as s:
        log = CampaignLog(s)
        assert log.find("k1") is None
        log.record("k1", 777)
        s.commit()
    with session_factory() as s:
        assert CampaignLog(s).find("k1") == 777


def test_alembic_builds_the_schema_on_an_empty_database(tmp_path):
    url = f"sqlite:///{tmp_path / 'fresh.db'}"
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    tables = set(inspect(create_engine(url)).get_table_names())
    assert {"flows", "created_campaigns"} <= tables
