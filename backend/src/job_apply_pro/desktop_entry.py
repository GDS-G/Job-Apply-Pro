from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

import uvicorn
from alembic import command
from alembic.config import Config

from job_apply_pro.config import get_settings
from job_apply_pro.domain.operations import RestoreConfirmation, RestoreStatus
from job_apply_pro.main import app
from job_apply_pro.services.backup import BackupError, BackupService
from job_apply_pro.storage.database import SessionFactory, engine
from job_apply_pro.storage.operations_repository import OperationsRepository


def _resource_path(name: str) -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    return (Path(frozen_root) if frozen_root else Path(__file__).parents[2]) / name


def migrate() -> None:
    configuration = Config(str(_resource_path("alembic.ini")))
    configuration.set_main_option("script_location", str(_resource_path("migrations")))
    command.upgrade(configuration, "head")


def serve() -> None:
    settings = get_settings()
    uvicorn.run(
        app,
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level.lower(),
        access_log=False,
    )


def restore(plan_id: str, fingerprint: str) -> None:
    """Apply an already-staged restore while the API process is stopped."""
    settings = get_settings()
    confirmation = RestoreConfirmation(
        fingerprint=fingerprint,
        confirmation_phrase=BackupService.RESTORE_PHRASE,
    )
    with SessionFactory() as session:
        repository = OperationsRepository(session)
        plan = repository.get_restore_plan(plan_id)
        manifest = repository.get_backup(plan.backup_id) if plan else None
    if plan is None:
        raise LookupError(f"Restore plan {plan_id} was not found")
    if manifest is None:
        raise LookupError(f"Backup manifest for restore plan {plan_id} was not found")
    if confirmation.fingerprint != plan.fingerprint:
        raise ValueError("Restore plan changed after review")

    staged = Path(plan.staged_path).resolve()
    staging_root = settings.restore_staging_dir.resolve()
    if not staged.is_dir() or staging_root not in staged.parents:
        raise BackupError("Restore staging directory is unavailable")

    # Release every SQLite handle before replacing the database file. The
    # supervisor guarantees the API server is stopped before this command runs.
    engine.dispose()
    BackupService.apply_staged_files(
        plan,
        database_url=settings.database_url,
        document_dir=settings.document_data_dir,
        staging_dir=settings.restore_staging_dir,
    )

    applied = plan.model_copy(
        update={"status": RestoreStatus.APPLIED, "applied_at": datetime.now(UTC)}
    )
    with SessionFactory() as session:
        repository = OperationsRepository(session)
        # The SQLite snapshot is captured immediately before its manifest is
        # persisted, so restore both records into the recovered database.
        repository.save_backup(manifest)
        repository.save_restore_plan(applied)


def main() -> None:
    parser = argparse.ArgumentParser(description="Job Apply Pro packaged backend")
    parser.add_argument("command", choices=("migrate", "serve", "restore"))
    parser.add_argument("--plan-id")
    parser.add_argument("--fingerprint")
    arguments = parser.parse_args()
    if arguments.command == "migrate":
        migrate()
    elif arguments.command == "serve":
        serve()
    else:
        if not arguments.plan_id or not arguments.fingerprint:
            parser.error("restore requires --plan-id and --fingerprint")
        restore(arguments.plan_id, arguments.fingerprint)


if __name__ == "__main__":
    main()
