from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from job_apply_pro.config import get_settings


def _configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> tuple[str, Config]:
    url = f"sqlite:///{(tmp_path / name).as_posix()}"
    monkeypatch.setenv("JAP_DATABASE_URL", url)
    monkeypatch.setenv("JAP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    return url, Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))


def test_external_effect_migration_has_exact_shape_and_is_repeatable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url, config = _configuration(tmp_path, monkeypatch, "external-effect-shape.db")
    engine = create_engine(url)
    try:
        command.upgrade(config, "20260913_0028")
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        inspector = inspect(engine)
        assert {"external_effect_operations", "external_effect_attempts"} <= set(
            inspector.get_table_names()
        )
        assert inspector.get_pk_constraint("external_effect_operations")["constrained_columns"] == [
            "id"
        ]
        assert any(
            item["column_names"] == ["claim_fingerprint"]
            for item in inspector.get_unique_constraints("external_effect_operations")
        )
        assert any(
            item["column_names"] == ["operation_id", "sequence"]
            for item in inspector.get_unique_constraints("external_effect_attempts")
        )
        assert {
            tuple(item["constrained_columns"])
            for item in inspector.get_foreign_keys("external_effect_attempts")
        } == {("operation_id",)}
        assert {
            tuple(item["column_names"])
            for item in inspector.get_indexes("external_effect_operations")
        } >= {
            ("kind",),
            ("status",),
            ("status", "updated_at"),
            ("subject_type", "subject_id", "created_at"),
        }
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "20260913_0029"
            )
            assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_external_effect_migration_downgrades_only_when_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url, config = _configuration(tmp_path, monkeypatch, "external-effect-empty.db")
    engine = create_engine(url)
    try:
        command.upgrade(config, "head")
        command.downgrade(config, "20260913_0028")
        assert "external_effect_operations" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_external_effect_migration_refuses_to_discard_retry_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url, config = _configuration(tmp_path, monkeypatch, "external-effect-history.db")
    engine = create_engine(url)
    try:
        command.upgrade(config, "head")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO external_effect_operations "
                    "(id,claim_fingerprint,kind,subject_type,subject_id,actor,"
                    "request_fingerprint,policy_version,status,created_at,updated_at) VALUES "
                    "(:id,:claim,'BROWSER_ACTION','browser_session','session-1','desktop-user',"
                    ":request,'external-effects-v1','PREPARED',:created,:created)"
                ),
                {
                    "id": "00000000-0000-4000-8000-000000000001",
                    "claim": "a" * 64,
                    "request": "b" * 64,
                    "created": "2026-09-14 00:00:00",
                },
            )
        with pytest.raises(RuntimeError, match="history prevents downgrade"):
            command.downgrade(config, "20260913_0028")
        assert "external_effect_operations" in inspect(engine).get_table_names()
    finally:
        engine.dispose()
        get_settings.cache_clear()
