from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from job_apply_pro.config import get_settings


def test_review_migration_preserves_legacy_requirements_without_approving_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = f"sqlite:///{(tmp_path / 'readiness-migration.db').as_posix()}"
    monkeypatch.setenv("JAP_DATABASE_URL", url)
    get_settings.cache_clear()
    config = Config("backend/alembic.ini")
    engine = create_engine(url)
    try:
        command.upgrade(config, "20260913_0025")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO jobs (id, source, external_id, employer, title, "
                    "description_hash, discovered_at) VALUES ('legacy', 'reference-ats', "
                    "'1', 'Fixture', 'Role', :digest, '2026-09-13 00:00:00')"
                ),
                {"digest": "a" * 64},
            )
            connection.execute(
                text(
                    "INSERT INTO job_requirements (id, job_id, category, text, required, "
                    "evidence_json) VALUES ('legacy-requirement', 'legacy', 'reference-ats', "
                    "'Python', 1, '{}')"
                )
            )
        command.upgrade(config, "20260913_0027")
        command.upgrade(config, "20260913_0027")
        assert "job_readiness_reviews" in inspect(engine).get_table_names()
        constraints = inspect(engine).get_unique_constraints("job_readiness_reviews")
        assert {item["name"] for item in constraints} == {
            "uq_readiness_review_revision",
            "uq_readiness_review_request",
        }
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT COUNT(*) FROM job_readiness_reviews")) == 0
            assert connection.scalar(text("SELECT text FROM job_requirements")) == "Python"
        command.downgrade(config, "20260913_0025")
        assert "job_readiness_reviews" not in inspect(engine).get_table_names()
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT text FROM job_requirements")) == "Python"
    finally:
        engine.dispose()
        get_settings.cache_clear()
