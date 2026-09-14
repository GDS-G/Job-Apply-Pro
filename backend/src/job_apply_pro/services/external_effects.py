import json
from datetime import UTC, datetime

from job_apply_pro.domain.external_effects import (
    ExternalEffectAdmission,
    ExternalEffectAttempt,
    ExternalEffectKind,
    ExternalEffectMetrics,
    ExternalEffectPublicRecord,
    ExternalEffectRecord,
    ExternalEffectStatus,
)
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.storage.external_effect_repository import ExternalEffectRepository


class ExternalEffectConsumedError(RuntimeError):
    def __init__(self, record: ExternalEffectRecord) -> None:
        super().__init__(
            f"External effect is already consumed with status {record.operation.status.value}"
        )
        self.record = record


class ExternalEffectService:
    POLICY_VERSION = "external-effects-v1"

    def __init__(self, repository: ExternalEffectRepository, cipher: SensitiveDataCipher) -> None:
        self._repository = repository
        self._cipher = cipher

    def admit(
        self,
        *,
        effect_key: str,
        kind: ExternalEffectKind,
        subject_type: str,
        subject_id: str,
        actor: str,
        request: object,
        policy_version: str | None = None,
        now: datetime | None = None,
    ) -> ExternalEffectAdmission:
        if not effect_key or len(effect_key) > 500 or any(ord(char) < 33 for char in effect_key):
            raise ValueError("External-effect key is invalid")
        now = now or datetime.now(UTC)
        return self._repository.prepare_operation(
            claim_fingerprint=self._fingerprint(
                effect_key.encode("utf-8"), context="external-effect-claim-v1"
            ),
            kind=kind,
            subject_type=subject_type,
            subject_id=subject_id,
            actor=actor,
            request_fingerprint=self.request_fingerprint(request),
            policy_version=policy_version or self.POLICY_VERSION,
            now=now,
        )

    def require_fresh(self, admission: ExternalEffectAdmission) -> ExternalEffectRecord:
        record = self._repository.get(admission.operation.id)
        if record is None:
            raise RuntimeError("Prepared external effect disappeared")
        if not admission.created:
            raise ExternalEffectConsumedError(record)
        return record

    def prepare_attempt(
        self,
        operation_id: str,
        *,
        provider: str,
        target_code: str,
        request: object,
        native_key: str | None = None,
        now: datetime | None = None,
    ) -> ExternalEffectAttempt:
        return self._repository.prepare_attempt(
            operation_id,
            provider=provider,
            target_code=target_code,
            request_fingerprint=self.request_fingerprint(request),
            native_key_fingerprint=(
                self._fingerprint(
                    native_key.encode("utf-8"), context="external-effect-native-key-v1"
                )
                if native_key is not None
                else None
            ),
            now=now or datetime.now(UTC),
        )

    def begin_dispatch(
        self, operation_id: str, attempt_id: str, *, now: datetime | None = None
    ) -> ExternalEffectRecord:
        return self._repository.begin_dispatch(
            operation_id, attempt_id, now=now or datetime.now(UTC)
        )

    def finish(
        self,
        operation_id: str,
        attempt_id: str,
        *,
        status: ExternalEffectStatus,
        result_reference: str | None = None,
        result: object | None = None,
        error_code: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cost_micros: int | None = None,
        continue_operation: bool = False,
        now: datetime | None = None,
    ) -> ExternalEffectRecord:
        result_fingerprint = self.request_fingerprint(result) if result is not None else None
        finish = (
            self._repository.finish_attempt_for_continuation
            if continue_operation
            else self._repository.finish_attempt_and_operation
        )
        return finish(
            operation_id,
            attempt_id,
            status=status,
            now=now or datetime.now(UTC),
            result_reference=result_reference,
            result_fingerprint=result_fingerprint,
            error_code=error_code,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_micros=cost_micros,
        )

    def request_fingerprint(self, value: object) -> str:
        return self._fingerprint(self._canonical(value), context="external-effect-request-v1")

    def recover_interrupted(self, *, now: datetime | None = None) -> int:
        return self._repository.recover_interrupted(now=now or datetime.now(UTC))

    def has_unresolved_subject(self, subject_type: str, subject_id: str) -> bool:
        return self._repository.has_unresolved_subject(subject_type, subject_id)

    def unresolved_subject_ids(self, *, kind: ExternalEffectKind, subject_type: str) -> list[str]:
        return self._repository.unresolved_subject_ids(kind=kind, subject_type=subject_type)

    def get(self, operation_id: str) -> ExternalEffectRecord | None:
        return self._repository.get(operation_id)

    def list_public(
        self,
        *,
        kind: ExternalEffectKind | None = None,
        status: ExternalEffectStatus | None = None,
        limit: int = 100,
    ) -> list[ExternalEffectPublicRecord]:
        return self._repository.list_public(kind=kind, status=status, limit=limit)

    def metrics(self) -> ExternalEffectMetrics:
        return self._repository.metrics()

    @staticmethod
    def _canonical(value: object) -> bytes:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

    def _fingerprint(self, value: bytes, *, context: str) -> str:
        return self._cipher.keyed_fingerprint(value, context=context)
