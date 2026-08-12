from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date
from typing import Protocol
from uuid import uuid4

from job_apply_pro.domain.applications import (
    ApplicationAnswerKind,
    ApplicationAnswerRecord,
    ApplicationAnswerStatus,
    ApplicationFieldBinding,
    ApplicationFieldBindingApproval,
    ApplicationFieldBindingPreview,
    ApplicationFieldBindingPreviewRequest,
    ApplicationFieldBindingRecord,
    FieldAutomationPermission,
    FieldBindingSource,
    ObservedPortalField,
    PortalFieldControlKind,
)
from job_apply_pro.domain.workflow import utc_now
from job_apply_pro.security.encryption import SensitiveDataCipher


class FieldBindingError(RuntimeError):
    pass


class FieldBindingConflictError(FieldBindingError):
    pass


class AnswerRepositoryProtocol(Protocol):
    def get_application_answer(self, answer_id: str) -> ApplicationAnswerRecord | None: ...


class BindingRepositoryProtocol(Protocol):
    def add(self, binding: ApplicationFieldBindingRecord) -> ApplicationFieldBindingRecord: ...

    def list_for_application(self, application_id: str) -> list[ApplicationFieldBindingRecord]: ...


_WORDS = re.compile(r"[a-z0-9]+", re.I)
_HUMAN_ONLY = {
    PortalFieldControlKind.FILE_UPLOAD,
    PortalFieldControlKind.SIGNATURE,
    PortalFieldControlKind.DISCLOSURE,
    PortalFieldControlKind.CUSTOM,
}


class ApplicationFieldBindingService:
    def __init__(
        self,
        answers: AnswerRepositoryProtocol,
        bindings: BindingRepositoryProtocol,
        cipher: SensitiveDataCipher,
    ) -> None:
        self._answers = answers
        self._bindings = bindings
        self._cipher = cipher

    def preview(
        self, command: ApplicationFieldBindingPreviewRequest
    ) -> ApplicationFieldBindingPreview:
        answer = self._answer(command.application_answer_id)
        field = command.observed_field
        errors = self._compatibility_errors(answer, field)
        label_words = self._words(field.label)
        canonical_words = self._words(answer.canonical_field.replace(".", " ").replace("_", " "))
        question = self._cipher.decrypt_bytes(
            answer.encrypted_question or "",
            context=f"application-answer:{answer.id}:question",
        ).decode()
        question_words = self._words(question)
        if canonical_words and canonical_words.issubset(label_words):
            confidence = 1.0
            source = FieldBindingSource.EXACT_CANONICAL_MATCH
        else:
            union = label_words | question_words
            confidence = len(label_words & question_words) / len(union) if union else 0.0
            source = FieldBindingSource.ANSWER_QUESTION_MATCH
        proposed = FieldAutomationPermission.PROHIBITED
        if not errors:
            proposed = (
                FieldAutomationPermission.REVIEW_REQUIRED
                if field.control_kind in _HUMAN_ONLY or field.legal_attestation
                else FieldAutomationPermission.AUTOFILL_ALLOWED
            )
        payload = self._fingerprint_payload(answer, field, confidence, source, errors, proposed)
        return ApplicationFieldBindingPreview(
            application_id=answer.application_id,
            application_answer_id=answer.id,
            answer_revision=answer.revision,
            portal=field.portal,
            page_fingerprint=field.page_fingerprint,
            control_key=field.control_key,
            control_kind=field.control_kind,
            label=field.label,
            required=field.required,
            options=field.options,
            canonical_field=answer.canonical_field,
            confidence=confidence,
            binding_source=source,
            answer_source=answer.source_type,
            answer_status=answer.status,
            answer_kind=answer.answer_kind,
            validation_rules=answer.validation_rules,
            compatible=not errors,
            validation_errors=errors,
            proposed_permission=proposed,
            review_fingerprint=self._fingerprint(payload),
        )

    def approve(self, command: ApplicationFieldBindingApproval) -> ApplicationFieldBinding:
        preview = self.preview(
            ApplicationFieldBindingPreviewRequest(
                application_answer_id=command.application_answer_id,
                observed_field=command.observed_field,
            )
        )
        if command.confirmation_phrase != "APPROVE FIELD BINDING":
            raise FieldBindingConflictError("Field binding confirmation phrase did not match")
        if command.expected_answer_revision != preview.answer_revision:
            raise FieldBindingConflictError(
                "Application answer changed; refresh the binding preview"
            )
        if command.review_fingerprint != preview.review_fingerprint:
            raise FieldBindingConflictError("Observed field or answer changed; refresh the preview")
        if not preview.compatible:
            raise FieldBindingConflictError("Incompatible portal fields cannot be approved")
        field = command.observed_field
        if command.automation_permission is FieldAutomationPermission.AUTOFILL_ALLOWED and (
            field.control_kind in _HUMAN_ONLY or field.legal_attestation
        ):
            raise FieldBindingConflictError("This control requires visible user handling")
        if command.automation_permission is FieldAutomationPermission.PROHIBITED:
            raise FieldBindingConflictError("A prohibited mapping is not an approved binding")
        now = utc_now()
        record = ApplicationFieldBindingRecord(
            id=str(uuid4()),
            application_id=preview.application_id,
            application_answer_id=preview.application_answer_id,
            answer_revision=preview.answer_revision,
            portal=preview.portal,
            page_fingerprint=preview.page_fingerprint,
            control_key=preview.control_key,
            control_kind=preview.control_kind,
            encrypted_label=self._cipher.encrypt_bytes(
                preview.label.encode(), context=f"field-binding:{preview.review_fingerprint}:label"
            ),
            encrypted_options=self._cipher.encrypt_bytes(
                json.dumps(preview.options).encode(),
                context=f"field-binding:{preview.review_fingerprint}:options",
            ),
            required=preview.required,
            canonical_field=preview.canonical_field,
            confidence=1.0,
            binding_source=FieldBindingSource.USER_CONFIRMED,
            answer_source=preview.answer_source,
            answer_kind=preview.answer_kind,
            validation_rules=preview.validation_rules,
            automation_permission=command.automation_permission,
            review_fingerprint=preview.review_fingerprint,
            created_at=now,
            updated_at=now,
        )
        try:
            saved = self._bindings.add(record)
        except ValueError as error:
            raise FieldBindingConflictError(str(error)) from error
        return self._public(saved)

    def list_bindings(self, application_id: str) -> list[ApplicationFieldBinding]:
        return [
            self._public(value) for value in self._bindings.list_for_application(application_id)
        ]

    def _answer(self, answer_id: str) -> ApplicationAnswerRecord:
        answer = self._answers.get_application_answer(answer_id)
        if answer is None:
            raise LookupError(f"Application answer {answer_id} was not found")
        return answer

    def _compatibility_errors(
        self, answer: ApplicationAnswerRecord, field: ObservedPortalField
    ) -> list[str]:
        errors: list[str] = []
        if answer.status not in {
            ApplicationAnswerStatus.REVIEWED,
            ApplicationAnswerStatus.PROMOTED,
        }:
            errors.append("Answer must be reviewed before binding")
        kind_controls = {
            ApplicationAnswerKind.NUMBER: {
                PortalFieldControlKind.NUMBER,
                PortalFieldControlKind.TEXT,
            },
            ApplicationAnswerKind.SALARY: {
                PortalFieldControlKind.NUMBER,
                PortalFieldControlKind.TEXT,
            },
            ApplicationAnswerKind.DATE: {PortalFieldControlKind.DATE, PortalFieldControlKind.TEXT},
            ApplicationAnswerKind.AVAILABILITY: {
                PortalFieldControlKind.DATE,
                PortalFieldControlKind.TEXT,
                PortalFieldControlKind.TEXT_AREA,
            },
            ApplicationAnswerKind.YES_NO: {
                PortalFieldControlKind.SELECT,
                PortalFieldControlKind.RADIO_GROUP,
                PortalFieldControlKind.CHECKBOX,
            },
            ApplicationAnswerKind.MULTIPLE_CHOICE: {
                PortalFieldControlKind.SELECT,
                PortalFieldControlKind.RADIO_GROUP,
            },
        }
        allowed = kind_controls.get(answer.answer_kind)
        if allowed is not None and field.control_kind not in allowed:
            errors.append(
                f"{answer.answer_kind.value} is incompatible with {field.control_kind.value}"
            )
        if answer.answer_kind is ApplicationAnswerKind.MULTIPLE_CHOICE:
            answer_choices = answer.validation_rules.get("choices")
            if not isinstance(answer_choices, list) or not field.options:
                errors.append("Choice bindings require observed and answer options")
            elif not set(str(value) for value in answer_choices).issubset(set(field.options)):
                errors.append("Answer choices are not all present in the observed control")
        answer_value = self._cipher.decrypt_bytes(
            answer.encrypted_value, context=f"application-answer:{answer.id}:value"
        ).decode()
        if field.character_limit is not None and len(answer_value) > field.character_limit:
            errors.append("Reviewed answer exceeds the observed character limit")
        if answer.answer_kind in {ApplicationAnswerKind.NUMBER, ApplicationAnswerKind.SALARY}:
            try:
                numeric = float(answer_value)
            except ValueError:
                errors.append("Reviewed answer is not numeric")
            else:
                if not math.isfinite(numeric):
                    errors.append("Reviewed answer is not finite")
                if field.minimum_number is not None and numeric < field.minimum_number:
                    errors.append("Reviewed answer is below the observed minimum")
                if field.maximum_number is not None and numeric > field.maximum_number:
                    errors.append("Reviewed answer is above the observed maximum")
        if answer.answer_kind in {ApplicationAnswerKind.DATE, ApplicationAnswerKind.AVAILABILITY}:
            try:
                parsed = date.fromisoformat(answer_value)
            except ValueError:
                if field.control_kind is PortalFieldControlKind.DATE:
                    errors.append("Reviewed answer is not an ISO date")
            else:
                if field.earliest_date and parsed < date.fromisoformat(field.earliest_date):
                    errors.append("Reviewed date precedes the observed minimum")
                if field.latest_date and parsed > date.fromisoformat(field.latest_date):
                    errors.append("Reviewed date follows the observed maximum")
        if (
            field.options
            and answer_value not in field.options
            and answer.answer_kind
            in {
                ApplicationAnswerKind.YES_NO,
                ApplicationAnswerKind.MULTIPLE_CHOICE,
            }
        ):
            errors.append("Reviewed answer is not an observed option")
        return errors

    @staticmethod
    def _words(value: str) -> set[str]:
        return {match.group(0).casefold() for match in _WORDS.finditer(value)}

    @staticmethod
    def _fingerprint_payload(
        answer: ApplicationAnswerRecord,
        field: ObservedPortalField,
        confidence: float,
        source: FieldBindingSource,
        errors: list[str],
        proposed: FieldAutomationPermission,
    ) -> dict[str, object]:
        return {
            "application_answer_id": answer.id,
            "answer_revision": answer.revision,
            "answer_kind": answer.answer_kind.value,
            "answer_source": answer.source_type.value,
            "answer_status": answer.status.value,
            "canonical_field": answer.canonical_field,
            "validation_rules": answer.validation_rules,
            "observed_field": field.model_dump(mode="json"),
            "confidence": confidence,
            "binding_source": source.value,
            "validation_errors": errors,
            "proposed_permission": proposed.value,
        }

    @staticmethod
    def _fingerprint(value: dict[str, object]) -> str:
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def _public(self, record: ApplicationFieldBindingRecord) -> ApplicationFieldBinding:
        label = self._cipher.decrypt_bytes(
            record.encrypted_label, context=f"field-binding:{record.review_fingerprint}:label"
        ).decode()
        options = json.loads(
            self._cipher.decrypt_bytes(
                record.encrypted_options,
                context=f"field-binding:{record.review_fingerprint}:options",
            ).decode()
        )
        return ApplicationFieldBinding(
            **record.model_dump(exclude={"encrypted_label", "encrypted_options"}),
            label=label,
            options=options,
        )
