from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from job_apply_pro.config import get_settings


def test_migration_preserves_every_legacy_payload_audit_and_claim_without_rebinding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = f"sqlite:///{(tmp_path / 'legacy-mail.db').as_posix()}"
    monkeypatch.setenv("JAP_DATABASE_URL", url)
    get_settings.cache_clear()
    config = Config("backend/alembic.ini")
    engine = create_engine(url)
    tables = [
        "communication_records",
        "outbound_drafts",
        "communication_mutation_audits",
        "mail_send_claims",
    ]
    try:
        command.upgrade(config, "20260913_0025")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO communication_records "
                    "(id,provider,provider_message_id,provider_thread_id,"
                    "category,requires_review,encrypted_analysis,received_at,created_at) VALUES "
                    "('record','GMAIL','message','thread','INTERVIEW_REQUEST',1,'legacy-ciphertext-unchanged',"
                    "'2026-09-13','2026-09-13')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO outbound_drafts "
                    "(id,analysis_id,provider,provider_thread_id,category,policy,"
                    "document_version_ids_json,fingerprint,encrypted_payload,"
                    "created_at,updated_at) "
                    "VALUES "
                    "('draft','record','GMAIL','thread','INTERVIEW_REQUEST','REVIEW_REQUIRED','[]',"
                    ":fingerprint,'legacy-draft-ciphertext-unchanged','2026-09-13','2026-09-13')"
                ),
                {"fingerprint": "a" * 64},
            )
            connection.execute(
                text(
                    "INSERT INTO communication_mutation_audits "
                    "(id,kind,provider,resource_id,idempotency_key,"
                    "fingerprint,status,confirmed_by,provider_resource_id,error_code,occurred_at) "
                    "VALUES "
                    "('audit','SEND_MESSAGE','GMAIL','draft','preserved-idempotency',:fingerprint,'UNCERTAIN',"
                    "'native-review',NULL,'ProviderSendUncertainError','2026-09-13')"
                ),
                {"fingerprint": "a" * 64},
            )
            connection.execute(
                text("INSERT INTO mail_send_claims(draft_id,audit_id) VALUES ('draft','audit')")
            )
            before = {
                table: list(connection.execute(text(f"SELECT * FROM {table}")).mappings())
                for table in tables
            }
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        constraints = inspect(engine).get_unique_constraints("communication_records")
        assert any(
            item["column_names"]
            == [
                "provider",
                "source_account_key",
                "source_connection_fingerprint",
                "provider_message_id",
            ]
            for item in constraints
        )
        with engine.connect() as connection:
            for table in tables:
                after = list(connection.execute(text(f"SELECT * FROM {table}")).mappings())
                if table == "communication_records":
                    assert after[0]["source_account_key"] == "0" * 64
                    assert after[0]["source_connection_fingerprint"] == "0" * 64
                    assert {key: after[0][key] for key in before[table][0]} == before[table][0]
                else:
                    assert after == before[table]
            assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
        # Legacy-only schema downgrade is lossless; modern provenance is not discarded.
        command.downgrade(config, "20260913_0025")
        command.upgrade(config, "head")
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE communication_records SET source_account_key=:key"), {"key": "b" * 64}
            )
        with pytest.raises(RuntimeError, match="pre-upgrade backup"):
            command.downgrade(config, "20260913_0025")
        with engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT source_account_key FROM communication_records"))
                == "b" * 64
            )
            assert connection.scalar(text("SELECT COUNT(*) FROM mail_send_claims")) == 1
    finally:
        engine.dispose()
        get_settings.cache_clear()
