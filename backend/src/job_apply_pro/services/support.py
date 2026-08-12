from datetime import UTC, datetime
from pathlib import Path

from job_apply_pro import __version__
from job_apply_pro.config import Settings
from job_apply_pro.domain.operations import PortalHealthMetric
from job_apply_pro.domain.support import StorageHealth, SupportDiagnostics
from job_apply_pro.portals.catalog import PORTAL_DEFINITIONS
from job_apply_pro.services.backup import BackupService
from job_apply_pro.storage.operations_repository import OperationsRepository
from job_apply_pro.storage.support_repository import SupportRepository


def _directory_bytes(root: Path) -> int:
    resolved_root = root.resolve()
    if not resolved_root.is_dir():
        return 0
    total = 0
    for path in resolved_root.rglob("*"):
        resolved = path.resolve()
        if path.is_symlink() or not path.is_file() or resolved_root not in resolved.parents:
            continue
        total += path.stat().st_size
    return total


def _database_bytes(database_url: str) -> int:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix) or database_url == "sqlite:///:memory:":
        return 0
    path = Path(database_url.removeprefix(prefix)).resolve()
    return path.stat().st_size if path.is_file() else 0


class SupportService:
    BUILD_NAME = "Native Gemini Fallback"

    def __init__(
        self,
        support: SupportRepository,
        operations: OperationsRepository,
        backups: BackupService,
        settings: Settings,
    ) -> None:
        self._support = support
        self._operations = operations
        self._backups = backups
        self._settings = settings

    def diagnostics(self) -> SupportDiagnostics:
        manifests = self._backups.list_backups()
        run_counts = self._operations.portal_run_counts()
        return SupportDiagnostics(
            generated_at=datetime.now(UTC),
            application_version=__version__,
            build_name=self.BUILD_NAME,
            schema_revision=BackupService.SCHEMA_REVISION,
            environment=self._settings.environment,
            process_status="READY",
            queue=self._support.queue_health(),
            recovery=self._support.recovery_health(),
            sessions=self._support.session_health(),
            storage=StorageHealth(
                database_bytes=_database_bytes(self._settings.database_url),
                documents_bytes=_directory_bytes(self._settings.document_data_dir),
                browser_artifacts_bytes=_directory_bytes(self._settings.browser_artifact_dir),
                backups_bytes=_directory_bytes(self._settings.backup_data_dir),
                restore_staging_bytes=_directory_bytes(self._settings.restore_staging_dir),
            ),
            backups_total=len(manifests),
            latest_backup_status=manifests[0].status.value if manifests else None,
            models=self._operations.model_metrics(),
            portals=[
                PortalHealthMetric(
                    portal=definition.kind.value,
                    support_status=definition.support_status.value,
                    production_enabled=definition.production_enabled,
                    run_count=run_counts.get(definition.kind.value, 0),
                    replay_validated_page_types=definition.replay_validated_page_types,
                    live_validated_page_types=definition.live_validated_page_types,
                    limitations=definition.limitations,
                )
                for definition in PORTAL_DEFINITIONS
            ],
            workflows=self._support.workflows(),
            errors=self._support.sanitized_errors(),
            traces=self._support.traces(),
        )
