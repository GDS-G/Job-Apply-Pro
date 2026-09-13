from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from job_apply_pro.config import get_settings


def test_snapshot_migration_round_trip_preserves_existing_jobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = f"sqlite:///{(tmp_path / 'synthetic-migration.db').as_posix()}"
    monkeypatch.setenv("JAP_DATABASE_URL", url)
    get_settings.cache_clear()
    config = Config("backend/alembic.ini")
    engine = create_engine(url)
    try:
        command.upgrade(config, "20260913_0024")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO jobs (id, source, external_id, employer, title, description_hash, "
                    "discovered_at) VALUES ('existing-job', 'fixture', '1', 'Fixture', "
                    "'Existing job', "
                    ":digest, '2026-09-13 00:00:00')"
                ),
                {"digest": "a" * 64},
            )
        for _ in range(2):
            command.upgrade(config, "head")
        inspector = inspect(engine)
        assert "job_discovery_snapshots" in inspector.get_table_names()
        assert inspector.get_pk_constraint("job_discovery_snapshots")["constrained_columns"] == [
            "job_id"
        ]
        assert inspector.get_foreign_keys("job_discovery_snapshots")[0]["referred_table"] == "jobs"
        with engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "20260913_0025"
            )
        command.downgrade(config, "20260913_0024")
        assert "job_discovery_snapshots" not in inspect(engine).get_table_names()
        with engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT title FROM jobs WHERE id='existing-job'"))
                == "Existing job"
            )
        command.upgrade(config, "head")
    finally:
        engine.dispose()
        get_settings.cache_clear()
