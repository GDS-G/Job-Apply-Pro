from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from job_apply_pro.config import get_settings


def test_migrations_are_repeatable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database_path = tmp_path / "migration-test.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("JAP_DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = Config("backend/alembic.ini")

    command.upgrade(config, "head")
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    tables = set(inspect(create_engine(database_url)).get_table_names())
    assert {
        "candidate_profiles",
        "jobs",
        "applications",
        "workflow_checkpoints",
        "workflow_events",
        "browser_sessions",
        "browser_actions",
        "documents",
        "document_versions",
        "evidence_sources",
        "candidate_claims",
        "answer_library",
        "retrieval_chunks",
        "ai_cache",
        "portal_runs",
        "challenge_sessions",
        "challenge_events",
        "backup_manifests",
        "backup_schedules",
        "restore_plans",
    } <= tables
    get_settings.cache_clear()
