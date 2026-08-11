import time
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from job_apply_pro.config import Settings
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.security.keys import StaticKeyProvider
from job_apply_pro.services.backup import BackupService
from job_apply_pro.services.support import SupportService
from job_apply_pro.storage.database import Base
from job_apply_pro.storage.models import ErrorRecordRow, JobRow
from job_apply_pro.storage.operations_repository import OperationsRepository
from job_apply_pro.storage.support_repository import SupportRepository


def _support_service(tmp_path: Path) -> tuple[Session, SupportService]:
    database_path = tmp_path / "job-apply-pro.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    session = Session(engine)
    documents = tmp_path / "documents"
    artifacts = tmp_path / "browser-artifacts"
    documents.mkdir()
    artifacts.mkdir()
    (documents / "candidate.jap").write_bytes(b"encrypted-envelope")
    (artifacts / "trace-metadata.txt").write_text("redacted", encoding="utf-8")
    settings = Settings(
        database_url=database_url,
        document_data_dir=documents,
        browser_artifact_dir=artifacts,
        backup_data_dir=tmp_path / "backups",
        restore_staging_dir=tmp_path / "restore-staging",
    )
    operations = OperationsRepository(session)
    backups = BackupService(
        operations,
        SensitiveDataCipher(StaticKeyProvider(b"s" * 32)),
        database_url=database_url,
        document_dir=documents,
        backup_dir=settings.backup_data_dir,
        staging_dir=settings.restore_staging_dir,
    )
    return session, SupportService(SupportRepository(session), operations, backups, settings)


def test_diagnostics_are_redacted_and_report_operational_health(tmp_path: Path) -> None:
    session, service = _support_service(tmp_path)
    session.add(
        ErrorRecordRow(
            id="error-1",
            workflow_id=None,
            classification="PROVIDER_TIMEOUT",
            component="fixture-provider",
            action="read messages",
            sanitized_context_json={
                "request_id": "request-value-must-not-export",
                "access_token": "token-value-must-not-export",
            },
            retry_count=2,
            created_at=datetime(2026, 8, 5, tzinfo=UTC),
        )
    )
    session.commit()

    diagnostics = service.diagnostics()
    encoded = diagnostics.model_dump_json()

    assert diagnostics.process_status == "READY"
    assert diagnostics.queue.total == 0
    assert diagnostics.storage.database_bytes > 0
    assert diagnostics.storage.documents_bytes == len(b"encrypted-envelope")
    assert diagnostics.storage.browser_artifacts_bytes == len(b"redacted")
    assert diagnostics.errors[0].context_keys == ["access_token", "request_id"]
    assert "request-value-must-not-export" not in encoded
    assert "token-value-must-not-export" not in encoded
    assert str(tmp_path) not in encoded
    assert all(not portal.production_enabled for portal in diagnostics.portals)
    session.close()


def test_metrics_remain_bounded_with_thousands_of_jobs(tmp_path: Path) -> None:
    session, service = _support_service(tmp_path)
    now = datetime(2026, 8, 5, tzinfo=UTC)
    session.add_all(
        JobRow(
            id=f"job-{index}",
            source="stress-fixture",
            external_id=f"external-{index}",
            employer=f"Employer {index % 25}",
            title=f"Role {index}",
            location="Remote",
            source_url=None,
            description_hash=f"{index:064x}"[-64:],
            discovered_at=now,
        )
        for index in range(2_000)
    )
    session.commit()

    started = time.perf_counter()
    diagnostics = service.diagnostics()
    elapsed = time.perf_counter() - started

    assert diagnostics.queue.total == 0
    assert elapsed < 3.0
    session.close()
