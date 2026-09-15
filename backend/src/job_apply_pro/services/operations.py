from datetime import UTC, datetime

from job_apply_pro.domain.communications import MessageCategory
from job_apply_pro.domain.external_effects import ExternalEffectStatus
from job_apply_pro.domain.operations import (
    InterviewReportRow,
    OperationsDashboard,
    PortalHealthMetric,
)
from job_apply_pro.portals.catalog import PORTAL_DEFINITIONS
from job_apply_pro.services.external_effects import ExternalEffectService
from job_apply_pro.services.licensing import LicenseService
from job_apply_pro.storage.communication_repository import CommunicationRepository
from job_apply_pro.storage.operations_repository import OperationsRepository


class OperationsService:
    ATTENTION_LIMIT = 20
    ATTENTION_STATUSES = (
        ExternalEffectStatus.PREPARED,
        ExternalEffectStatus.DISPATCHING,
        ExternalEffectStatus.UNCERTAIN,
    )

    def __init__(
        self,
        repository: OperationsRepository,
        communications: CommunicationRepository,
        licensing: LicenseService,
        external_effects: ExternalEffectService,
    ) -> None:
        self._repository = repository
        self._communications = communications
        self._licensing = licensing
        self._external_effects = external_effects

    def dashboard(self) -> OperationsDashboard:
        backups = self._repository.list_backups()
        run_counts = self._repository.portal_run_counts()
        records = self._communications.list_records()
        unresolved_external_effects = sorted(
            (
                record
                for effect_status in self.ATTENTION_STATUSES
                for record in self._external_effects.list_public(
                    status=effect_status,
                    limit=self.ATTENTION_LIMIT,
                )
            ),
            key=lambda record: (record.created_at, record.id),
            reverse=True,
        )[: self.ATTENTION_LIMIT]
        interview_categories = {
            MessageCategory.RECRUITER_INQUIRY,
            MessageCategory.SCREENING_REQUEST,
            MessageCategory.INTERVIEW_REQUEST,
            MessageCategory.ASSESSMENT_INVITATION,
            MessageCategory.OFFER,
        }
        return OperationsDashboard(
            generated_at=datetime.now(UTC),
            applications=self._repository.application_metrics(),
            models=self._repository.model_metrics(),
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
            application_report=self._repository.application_report(),
            interview_report=[
                InterviewReportRow(
                    communication_id=record.id,
                    workflow_id=record.analysis.correlation.workflow_id,
                    category=record.analysis.classification.category.value,
                    sender=record.analysis.message.sender,
                    subject=record.analysis.message.subject,
                    received_at=record.received_at,
                )
                for record in records
                if record.analysis.classification.category in interview_categories
            ],
            external_effects=self._external_effects.metrics(),
            unresolved_external_effects=unresolved_external_effects,
            backup_count=len(backups),
            latest_backup=backups[0] if backups else None,
            license=self._licensing.state(),
        )
