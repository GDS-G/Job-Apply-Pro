from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path, PureWindowsPath


def _resource_path(name: str) -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    return (Path(frozen_root) if frozen_root else Path(__file__).parents[2]) / name


def _configure_worker_browser_cache() -> None:
    """Use the installed Windows cache instead of a nonexistent frozen bundle cache."""
    if not getattr(sys, "frozen", False) or sys.platform != "win32":
        return
    if "PLAYWRIGHT_BROWSERS_PATH" in os.environ:
        return
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    directory = PureWindowsPath(local_app_data)
    if (
        not local_app_data
        or local_app_data != local_app_data.strip()
        or not directory.is_absolute()
        or ".." in directory.parts
        or any(ord(character) < 32 for character in local_app_data)
    ):
        raise ValueError(
            "LOCALAPPDATA must be an absolute Windows directory for the installed browser cache"
        )
    # Do not download browsers or create the cache. A missing installed browser
    # remains an ordinary controlled launch failure. An explicit override,
    # including Playwright's hermetic '0', is always left unchanged.
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(directory / "ms-playwright")


def migrate() -> None:
    from job_apply_pro.config import get_settings
    from job_apply_pro.restore_admission import runtime_access

    with runtime_access(get_settings()):
        _migrate_owned()


def _migrate_owned() -> None:
    from alembic import command
    from alembic.config import Config

    configuration = Config(str(_resource_path("alembic.ini")))
    configuration.set_main_option("script_location", str(_resource_path("migrations")))
    command.upgrade(configuration, "head")


def serve() -> None:
    from job_apply_pro.config import get_settings
    from job_apply_pro.restore_admission import runtime_access

    settings = get_settings()
    with runtime_access(settings):
        import uvicorn

        from job_apply_pro.main import app

        uvicorn.run(
            app,
            host=settings.api_host,
            port=settings.api_port,
            log_level=settings.log_level.lower(),
            access_log=False,
        )


def restore(plan_id: str, fingerprint: str) -> None:
    """Apply an already-staged restore while the API process is stopped."""
    from job_apply_pro.config import get_settings
    from job_apply_pro.restore_admission import closed_restore_database_path, workspace_roots
    from job_apply_pro.storage.restore_gate_repository import (
        RestoreAdmissionError,
        RestoreGateRepository,
        workspace_access,
    )

    roots = workspace_roots(get_settings())
    if len(roots) != 1:
        raise RestoreAdmissionError(
            "Restore requires one app-owned SQLite workspace; "
            "external paths must be reviewed before restoring"
        )
    with workspace_access(roots[0], restore=True):
        RestoreGateRepository(roots[0]).assert_clear()
        # BackupService imports storage models, so check paths before importing it.
        closed_restore_database_path(get_settings().database_url)
        from job_apply_pro.services.backup import BackupError

        try:
            _restore_owned(plan_id, fingerprint, roots[0])
        except BackupError as error:
            raise RestoreAdmissionError(str(error)) from None


def _restore_owned(plan_id: str, fingerprint: str, root: Path) -> None:
    from job_apply_pro.config import get_settings
    from job_apply_pro.restore_admission import closed_restore_database_path

    settings = get_settings()
    database = closed_restore_database_path(settings.database_url)

    from job_apply_pro.domain.operations import RestorePlan
    from job_apply_pro.security.encryption import SensitiveDataCipher
    from job_apply_pro.security.keys import EnvironmentKeyProvider
    from job_apply_pro.services.restore_recovery import RestoreRecoveryService
    from job_apply_pro.storage.database import SessionFactory, engine
    from job_apply_pro.storage.operations_repository import OperationsRepository

    with SessionFactory() as session:
        repository = OperationsRepository(session)
        plan = repository.get_restore_plan(plan_id)
        manifest = repository.get_backup(plan.backup_id) if plan else None
    if plan is None:
        raise LookupError(f"Restore plan {plan_id} was not found")
    if manifest is None:
        raise LookupError(f"Backup manifest for restore plan {plan_id} was not found")
    if fingerprint != plan.fingerprint:
        raise ValueError("Restore plan changed after review")
    engine.dispose()
    recovery = RestoreRecoveryService(root, SensitiveDataCipher(EnvironmentKeyProvider()))
    intent = recovery.prepare(
        plan,
        manifest,
        database=database,
        documents=settings.document_data_dir,
        staging=settings.restore_staging_dir,
        backups=settings.backup_data_dir,
    )

    def commit_result(applied: RestorePlan) -> None:
        try:
            with SessionFactory() as session:
                OperationsRepository(session).save_restore_result(manifest, applied)
        finally:
            engine.dispose()

    recovery.apply(intent, commit_result)


def restore_status() -> bool:
    """Key-free and DB-free: even malformed sentinels remain visibly blocked."""
    from job_apply_pro.config import get_settings
    from job_apply_pro.restore_admission import workspace_roots
    from job_apply_pro.storage.restore_gate_repository import (
        RestoreAdmissionError,
        RestoreGateRepository,
    )

    try:
        roots = workspace_roots(get_settings())
        blocked = any(RestoreGateRepository(root).blocked() for root in roots)
    except (OSError, RestoreAdmissionError):
        blocked = True
    if sys.stdout is not None:
        print(json.dumps({"restore_recovery_required": blocked}))
    return blocked


def restore_finalize(operation_id: str) -> None:
    from job_apply_pro.config import get_settings
    from job_apply_pro.restore_admission import workspace_roots
    from job_apply_pro.security.encryption import SensitiveDataCipher
    from job_apply_pro.security.keys import EnvironmentKeyProvider
    from job_apply_pro.services.restore_recovery import RestoreRecoveryService
    from job_apply_pro.storage.restore_gate_repository import RestoreAdmissionError

    roots = workspace_roots(get_settings())
    if len(roots) != 1:
        raise RestoreAdmissionError("Recovery requires the original app-owned workspace layout")
    RestoreRecoveryService(roots[0], SensitiveDataCipher(EnvironmentKeyProvider())).finalize(
        operation_id
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Job Apply Pro packaged backend")
    parser.add_argument(
        "command",
        choices=(
            "migrate",
            "serve",
            "restore",
            "restore-status",
            "restore-finalize",
            "browser-worker",
        ),
    )
    parser.add_argument("--plan-id")
    parser.add_argument("--fingerprint")
    parser.add_argument("--operation-id")
    arguments = parser.parse_args()
    if arguments.command == "browser-worker":
        if arguments.plan_id or arguments.fingerprint or arguments.operation_id:
            parser.error("browser-worker does not accept restore arguments")
        if sys.stdin is None or sys.stdout is None:
            parser.error("browser-worker requires usable standard input and output")
        try:
            _configure_worker_browser_cache()
        except ValueError as error:
            parser.error(str(error))
        # The console-capable worker EXE shares this entry stage and module
        # archive, but must not initialize the API, database, or migration code.
        from job_apply_pro.browser.worker_process import main as worker_main

        worker_main()
    elif arguments.command == "restore-status":
        if restore_status():
            raise SystemExit(3)
    elif arguments.command == "restore-finalize":
        if not arguments.operation_id:
            parser.error("restore-finalize requires --operation-id")
        restore_finalize(arguments.operation_id)
    elif arguments.command == "migrate":
        migrate()
    elif arguments.command == "serve":
        serve()
    else:
        if not arguments.plan_id or not arguments.fingerprint:
            parser.error("restore requires --plan-id and --fingerprint")
        restore(arguments.plan_id, arguments.fingerprint)


if __name__ == "__main__":
    from sqlalchemy.exc import SQLAlchemyError

    from job_apply_pro.security.keys import KeyConfigurationError
    from job_apply_pro.storage.restore_gate_repository import RestoreAdmissionError

    try:
        main()
    except (
        RestoreAdmissionError,
        KeyConfigurationError,
        OSError,
        ValueError,
        LookupError,
        SQLAlchemyError,
    ):
        if sys.stderr is not None:
            print(
                "Offline restore admission failed. Preserve the original workspace, backup, "
                "staging files and key. Run restore-status without opening the database; "
                "authenticated completion or manual recovery review is required.",
                file=sys.stderr,
            )
        raise SystemExit(3) from None
