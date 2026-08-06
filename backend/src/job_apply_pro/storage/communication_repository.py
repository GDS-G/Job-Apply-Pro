from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_apply_pro.domain.communications import (
    CalendarEventSnapshot,
    CalendarMutationPlan,
    CommunicationAnalysis,
    CommunicationRecord,
    FollowUp,
    FollowUpStatus,
    IntegrationProvider,
    MessageCategory,
    MutationAudit,
    MutationKind,
    MutationStatus,
    OutboundDraft,
    OutboundPolicy,
)
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.storage.models import (
    CalendarMutationPlanRow,
    CommunicationMutationAuditRow,
    CommunicationRecordRow,
    FollowUpRow,
    OutboundDraftRow,
)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class CommunicationRepository:
    def __init__(self, session: Session, cipher: SensitiveDataCipher) -> None:
        self._session = session
        self._cipher = cipher

    def save_record(self, record: CommunicationRecord) -> CommunicationRecord:
        existing = self._session.scalar(
            select(CommunicationRecordRow).where(
                CommunicationRecordRow.provider == record.analysis.message.provider.value,
                CommunicationRecordRow.provider_message_id
                == record.analysis.message.provider_message_id,
            )
        )
        if existing is not None:
            return self._record(existing)
        self._session.add(
            CommunicationRecordRow(
                id=record.id,
                provider=record.analysis.message.provider.value,
                provider_message_id=record.analysis.message.provider_message_id,
                provider_thread_id=record.analysis.message.provider_thread_id,
                category=record.analysis.classification.category.value,
                workflow_id=record.analysis.correlation.workflow_id,
                requires_review=(
                    record.analysis.classification.requires_review
                    or record.analysis.correlation.requires_review
                ),
                encrypted_analysis=self._cipher.encrypt_json(
                    record.analysis.model_dump(mode="json"),
                    context=f"communication:{record.id}:analysis",
                ),
                received_at=record.received_at,
                created_at=record.created_at,
            )
        )
        self._session.commit()
        return record

    def get_record(self, record_id: str) -> CommunicationRecord | None:
        row = self._session.get(CommunicationRecordRow, record_id)
        return self._record(row) if row else None

    def list_records(self) -> list[CommunicationRecord]:
        rows = self._session.scalars(
            select(CommunicationRecordRow).order_by(CommunicationRecordRow.received_at.desc())
        ).all()
        return [self._record(row) for row in rows]

    def save_draft(self, draft: OutboundDraft) -> OutboundDraft:
        self._session.add(
            OutboundDraftRow(
                id=draft.id,
                analysis_id=draft.analysis_id,
                workflow_id=draft.workflow_id,
                provider=draft.provider.value,
                provider_thread_id=draft.provider_thread_id,
                category=draft.category.value,
                policy=draft.policy.value,
                document_version_ids_json=draft.document_version_ids,
                fingerprint=draft.fingerprint,
                encrypted_payload=self._cipher.encrypt_json(
                    {
                        "recipient": draft.recipient,
                        "subject": draft.subject,
                        "body_text": draft.body_text,
                    },
                    context=f"communication-draft:{draft.id}:payload",
                ),
                created_at=draft.created_at,
                updated_at=draft.updated_at,
            )
        )
        self._session.commit()
        return draft

    def get_draft(self, draft_id: str) -> OutboundDraft | None:
        row = self._session.get(OutboundDraftRow, draft_id)
        return self._draft(row) if row else None

    def list_drafts(self) -> list[OutboundDraft]:
        rows = self._session.scalars(
            select(OutboundDraftRow).order_by(OutboundDraftRow.updated_at.desc())
        ).all()
        return [self._draft(row) for row in rows]

    def save_calendar_plan(self, plan: CalendarMutationPlan) -> CalendarMutationPlan:
        self._session.add(
            CalendarMutationPlanRow(
                id=plan.id,
                provider=plan.provider.value,
                workflow_id=plan.workflow_id,
                kind=plan.kind.value,
                fingerprint=plan.fingerprint,
                encrypted_payload=self._cipher.encrypt_json(
                    {
                        "event": plan.event.model_dump(mode="json"),
                        "prior_event": (
                            plan.prior_event.model_dump(mode="json")
                            if plan.prior_event is not None
                            else None
                        ),
                    },
                    context=f"calendar-plan:{plan.id}:payload",
                ),
                created_at=plan.created_at,
            )
        )
        self._session.commit()
        return plan

    def get_calendar_plan(self, plan_id: str) -> CalendarMutationPlan | None:
        row = self._session.get(CalendarMutationPlanRow, plan_id)
        if row is None:
            return None
        payload = self._cipher.decrypt_json(
            row.encrypted_payload, context=f"calendar-plan:{row.id}:payload"
        )
        return CalendarMutationPlan(
            id=row.id,
            provider=IntegrationProvider(row.provider),
            workflow_id=row.workflow_id,
            event=CalendarEventSnapshot.model_validate(payload["event"]),
            prior_event=(
                CalendarEventSnapshot.model_validate(payload["prior_event"])
                if payload["prior_event"] is not None
                else None
            ),
            kind=MutationKind(row.kind),
            fingerprint=row.fingerprint,
            created_at=_utc(row.created_at),
        )

    def add_audit(self, audit: MutationAudit) -> MutationAudit:
        row = self._session.scalar(
            select(CommunicationMutationAuditRow).where(
                CommunicationMutationAuditRow.idempotency_key == audit.idempotency_key
            )
        )
        if row is None:
            row = CommunicationMutationAuditRow(
                id=audit.id,
                kind=audit.kind.value,
                provider=audit.provider.value,
                resource_id=audit.resource_id,
                idempotency_key=audit.idempotency_key,
                fingerprint=audit.fingerprint,
                status=audit.status.value,
                confirmed_by=audit.confirmed_by,
                provider_resource_id=audit.provider_resource_id,
                error_code=audit.error_code,
                occurred_at=audit.occurred_at,
            )
            self._session.add(row)
        else:
            row.status = audit.status.value
            row.confirmed_by = audit.confirmed_by
            row.provider_resource_id = audit.provider_resource_id
            row.error_code = audit.error_code
            row.occurred_at = audit.occurred_at
        self._session.commit()
        return audit

    def find_audit_by_idempotency(self, key: str) -> MutationAudit | None:
        row = self._session.scalar(
            select(CommunicationMutationAuditRow).where(
                CommunicationMutationAuditRow.idempotency_key == key
            )
        )
        return self._audit(row) if row else None

    def list_audits(self) -> list[MutationAudit]:
        rows = self._session.scalars(
            select(CommunicationMutationAuditRow).order_by(
                CommunicationMutationAuditRow.occurred_at.desc()
            )
        ).all()
        return [self._audit(row) for row in rows]

    def save_follow_up(self, follow_up: FollowUp) -> FollowUp:
        existing = self._session.scalar(
            select(FollowUpRow).where(FollowUpRow.dedupe_key == follow_up.dedupe_key)
        )
        if existing is not None:
            return self._follow_up(existing)
        self._session.add(
            FollowUpRow(
                id=follow_up.id,
                workflow_id=follow_up.workflow_id,
                reason=follow_up.reason,
                due_at=follow_up.due_at,
                channel=follow_up.channel.value,
                status=follow_up.status.value,
                dedupe_key=follow_up.dedupe_key,
                created_at=follow_up.created_at,
                updated_at=follow_up.updated_at,
            )
        )
        self._session.commit()
        return follow_up

    def list_follow_ups(self) -> list[FollowUp]:
        rows = self._session.scalars(select(FollowUpRow).order_by(FollowUpRow.due_at)).all()
        return [self._follow_up(row) for row in rows]

    def _record(self, row: CommunicationRecordRow) -> CommunicationRecord:
        payload = self._cipher.decrypt_json(
            row.encrypted_analysis, context=f"communication:{row.id}:analysis"
        )
        return CommunicationRecord(
            id=row.id,
            analysis=CommunicationAnalysis.model_validate(payload),
            received_at=_utc(row.received_at),
            created_at=_utc(row.created_at),
        )

    def _draft(self, row: OutboundDraftRow) -> OutboundDraft:
        payload = self._cipher.decrypt_json(
            row.encrypted_payload, context=f"communication-draft:{row.id}:payload"
        )
        return OutboundDraft(
            id=row.id,
            analysis_id=row.analysis_id,
            workflow_id=row.workflow_id,
            provider=IntegrationProvider(row.provider),
            provider_thread_id=row.provider_thread_id,
            recipient=str(payload["recipient"]),
            subject=str(payload["subject"]),
            body_text=str(payload["body_text"]),
            category=MessageCategory(row.category),
            policy=OutboundPolicy(row.policy),
            document_version_ids=row.document_version_ids_json,
            fingerprint=row.fingerprint,
            created_at=_utc(row.created_at),
            updated_at=_utc(row.updated_at),
        )

    @staticmethod
    def _audit(row: CommunicationMutationAuditRow) -> MutationAudit:
        return MutationAudit(
            id=row.id,
            kind=MutationKind(row.kind),
            provider=IntegrationProvider(row.provider),
            resource_id=row.resource_id,
            idempotency_key=row.idempotency_key,
            fingerprint=row.fingerprint,
            status=MutationStatus(row.status),
            confirmed_by=row.confirmed_by,
            provider_resource_id=row.provider_resource_id,
            error_code=row.error_code,
            occurred_at=_utc(row.occurred_at),
        )

    @staticmethod
    def _follow_up(row: FollowUpRow) -> FollowUp:
        return FollowUp(
            id=row.id,
            workflow_id=row.workflow_id,
            reason=row.reason,
            due_at=_utc(row.due_at),
            channel=IntegrationProvider(row.channel),
            status=FollowUpStatus(row.status),
            dedupe_key=row.dedupe_key,
            created_at=_utc(row.created_at),
            updated_at=_utc(row.updated_at),
        )
