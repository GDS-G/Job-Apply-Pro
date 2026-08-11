import base64
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from job_apply_pro.domain.operations import (
    BackupCategory,
    BackupCreate,
    RestoreCreate,
    RestoreStatus,
)
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.security.keys import StaticKeyProvider
from job_apply_pro.services.backup import BackupService
from job_apply_pro.storage.database import Base
from job_apply_pro.storage.operations_repository import OperationsRepository


def test_offline_restore_cli_replaces_closed_database_and_restarts_state(
    tmp_path: Path,
) -> None:
    database = tmp_path / "job-apply-pro.db"
    database_url = f"sqlite:///{database.as_posix()}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    documents = tmp_path / "documents"
    documents.mkdir()
    document = documents / "resume.enc"
    document.write_text("verified-encrypted-document", encoding="utf-8")
    session = Session(engine)
    service = BackupService(
        OperationsRepository(session),
        SensitiveDataCipher(StaticKeyProvider(b"r" * 32, key_id="local-v1")),
        database_url=database_url,
        document_dir=documents,
        backup_dir=tmp_path / "backups",
        staging_dir=tmp_path / "restore-staging",
    )
    manifest = service.create(BackupCreate(label="CLI rollback drill"))
    plan = service.stage_restore(
        manifest.id,
        RestoreCreate(categories={BackupCategory.DATABASE, BackupCategory.DOCUMENTS}),
    )
    document.write_text("damaged", encoding="utf-8")
    session.close()
    engine.dispose()

    environment = {
        **os.environ,
        "JAP_DATABASE_URL": database_url,
        "JAP_DOCUMENT_DATA_DIR": str(documents),
        "JAP_BACKUP_DATA_DIR": str(tmp_path / "backups"),
        "JAP_RESTORE_STAGING_DIR": str(tmp_path / "restore-staging"),
        "JAP_BROWSER_DATA_DIR": str(tmp_path / "browser"),
        "JAP_BROWSER_ARTIFACT_DIR": str(tmp_path / "browser-artifacts"),
        "JAP_MASTER_KEY": base64.urlsafe_b64encode(b"r" * 32).decode("ascii"),
        "PYTHONPATH": str(Path(__file__).parents[1] / "src"),
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "job_apply_pro.desktop_entry",
            "restore",
            "--plan-id",
            plan.id,
            "--fingerprint",
            plan.fingerprint,
        ],
        cwd=Path(__file__).parents[2],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert document.read_text(encoding="utf-8") == "verified-encrypted-document"
    assert database.with_suffix(".db.pre-restore").is_file()
    recovered_engine = create_engine(database_url)
    with Session(recovered_engine) as recovered_session:
        repository = OperationsRepository(recovered_session)
        assert repository.get_backup(manifest.id) is not None
        assert repository.get_restore_plan(plan.id).status is RestoreStatus.APPLIED  # type: ignore[union-attr]
    recovered_engine.dispose()
