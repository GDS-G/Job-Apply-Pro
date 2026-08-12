from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from job_apply_pro.domain.applications import (
    ApplicationAnswerKind,
    ApplicationAnswerSource,
    ApplicationFieldBindingRecord,
    FieldAutomationPermission,
    FieldBindingSource,
    PortalFieldControlKind,
)
from job_apply_pro.storage.models import ApplicationFieldBindingRow


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _record(row: ApplicationFieldBindingRow) -> ApplicationFieldBindingRecord:
    return ApplicationFieldBindingRecord(
        id=row.id,
        application_id=row.application_id,
        application_answer_id=row.application_answer_id,
        answer_revision=row.answer_revision,
        portal=row.portal,
        page_fingerprint=row.page_fingerprint,
        control_key=row.control_key,
        control_kind=PortalFieldControlKind(row.control_kind),
        encrypted_label=row.encrypted_label,
        encrypted_options=row.encrypted_options,
        required=row.required,
        canonical_field=row.canonical_field,
        confidence=row.confidence,
        binding_source=FieldBindingSource(row.binding_source),
        answer_source=ApplicationAnswerSource(row.answer_source),
        answer_kind=ApplicationAnswerKind(row.answer_kind),
        validation_rules=row.validation_rules_json,
        automation_permission=FieldAutomationPermission(row.automation_permission),
        review_fingerprint=row.review_fingerprint,
        created_at=_utc(row.created_at),
        updated_at=_utc(row.updated_at),
    )


class ApplicationFieldBindingRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, binding: ApplicationFieldBindingRecord) -> ApplicationFieldBindingRecord:
        try:
            self._session.add(
                ApplicationFieldBindingRow(
                    id=binding.id,
                    application_id=binding.application_id,
                    application_answer_id=binding.application_answer_id,
                    answer_revision=binding.answer_revision,
                    portal=binding.portal,
                    page_fingerprint=binding.page_fingerprint,
                    control_key=binding.control_key,
                    control_kind=binding.control_kind.value,
                    encrypted_label=binding.encrypted_label,
                    encrypted_options=binding.encrypted_options,
                    required=binding.required,
                    canonical_field=binding.canonical_field,
                    confidence=binding.confidence,
                    binding_source=binding.binding_source.value,
                    answer_source=binding.answer_source.value,
                    answer_kind=binding.answer_kind.value,
                    validation_rules_json=binding.validation_rules,
                    automation_permission=binding.automation_permission.value,
                    review_fingerprint=binding.review_fingerprint,
                    created_at=binding.created_at,
                    updated_at=binding.updated_at,
                )
            )
            self._session.commit()
        except IntegrityError as error:
            self._session.rollback()
            raise ValueError("This observed portal control is already bound") from error
        return binding

    def list_for_application(self, application_id: str) -> list[ApplicationFieldBindingRecord]:
        rows = self._session.scalars(
            select(ApplicationFieldBindingRow)
            .where(ApplicationFieldBindingRow.application_id == application_id)
            .order_by(ApplicationFieldBindingRow.created_at.desc())
        ).all()
        return [_record(row) for row in rows]
