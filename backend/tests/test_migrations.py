from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from job_apply_pro.config import get_settings


def test_migrations_are_repeatable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database_path = tmp_path / "migration-test.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("JAP_DATABASE_URL", database_url)
    get_settings.cache_clear()


def test_answer_revision_migration_backfills_ciphertext_without_decryption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "answer-revision-migration.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("JAP_DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = Config("backend/alembic.ini")
    command.upgrade(config, "20260812_0017")
    engine = create_engine(database_url)
    ciphertext = "jap:v1:existing-ciphertext"
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO candidate_profiles (
                    id, display_name, encrypted_contact, status, created_at, updated_at
                ) VALUES (
                    :id, :display_name, :contact, :status, :created_at, :updated_at
                )
                """
            ),
            {
                "id": "profile-before-revisions",
                "display_name": "Migration fixture",
                "contact": ciphertext,
                "status": "ACTIVE",
                "created_at": "2026-08-12 00:00:00",
                "updated_at": "2026-08-12 00:00:00",
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO answer_library (
                    id, profile_id, canonical_field, encrypted_question,
                    encrypted_answer, evidence_claim_ids_json, confidence,
                    approved, locked, reuse_permission, provenance_json,
                    created_at, updated_at
                ) VALUES (
                    :id, :profile_id, :canonical_field, :question,
                    :answer, :evidence, :confidence,
                    :approved, :locked, :permission, :provenance,
                    :created_at, :updated_at
                )
                """
            ),
            {
                "id": "answer-before-revisions",
                "profile_id": "profile-before-revisions",
                "canonical_field": "work.authorization",
                "question": ciphertext,
                "answer": ciphertext,
                "evidence": "[]",
                "confidence": 1.0,
                "approved": True,
                "locked": True,
                "permission": "APPLICATIONS",
                "provenance": "{}",
                "created_at": "2026-08-12 00:00:00",
                "updated_at": "2026-08-12 01:00:00",
            },
        )
    command.upgrade(config, "head")
    with engine.connect() as connection:
        current = connection.execute(
            text("SELECT revision, encrypted_answer FROM answer_library")
        ).one()
        historical = connection.execute(
            text("SELECT id, answer_id, revision, encrypted_answer FROM answer_library_revisions")
        ).one()
    assert current == (1, ciphertext)
    assert historical == (
        "answer-before-revisions",
        "answer-before-revisions",
        1,
        ciphertext,
    )
    get_settings.cache_clear()
    config = Config("backend/alembic.ini")

    command.upgrade(config, "head")
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    inspector = inspect(create_engine(database_url))
    tables = set(inspector.get_table_names())
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
        "document_generation_audits",
        "document_selection_audits",
        "answer_library_revisions",
        "submitted_document_evidence",
        "communication_configurations",
        "provider_sync_states",
        "provider_calendar_events",
    } <= tables
    audit_columns = {
        column["name"] for column in inspector.get_columns("document_generation_audits")
    }
    assert {"template", "ranking_mode", "ranking_method"} <= audit_columns
    get_settings.cache_clear()
