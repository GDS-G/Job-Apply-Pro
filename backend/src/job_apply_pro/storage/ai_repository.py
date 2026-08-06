from sqlalchemy.orm import Session

from job_apply_pro.domain.ai import (
    AICacheRecord,
    AIInvocationRecord,
    DataClassification,
)
from job_apply_pro.storage.models import AICacheRow, ModelInvocationRow


class AIGatewayRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_invocation(self, invocation: AIInvocationRecord) -> AIInvocationRecord:
        self._session.add(
            ModelInvocationRow(
                id=invocation.id,
                profile_id=invocation.profile_id,
                task_type=invocation.task_type.value,
                provider=invocation.provider_id,
                model=invocation.model_id,
                prompt_version=invocation.prompt_version,
                schema_version=invocation.schema_version,
                input_hash=invocation.input_hash,
                cache_key=invocation.cache_key,
                classification=invocation.classification.value,
                status=invocation.status,
                input_tokens=invocation.input_tokens,
                output_tokens=invocation.output_tokens,
                cost_micros=invocation.cost_micros,
                attempts=invocation.attempts,
                route_json=invocation.route,
                latency_ms=invocation.latency_ms,
                error_code=invocation.error_code,
                created_at=invocation.created_at,
                completed_at=invocation.completed_at,
            )
        )
        self._session.commit()
        return invocation

    def get_cache(self, key: str) -> AICacheRecord | None:
        row = self._session.get(AICacheRow, key)
        return self._cache_record(row) if row is not None else None

    def upsert_cache(self, record: AICacheRecord) -> AICacheRecord:
        row = self._session.get(AICacheRow, record.key)
        if row is None:
            row = AICacheRow(
                key=record.key,
                profile_id=record.profile_id,
                classification=record.classification.value,
                encrypted_response=record.encrypted_response,
                expires_at=record.expires_at,
                created_at=record.created_at,
            )
            self._session.add(row)
        else:
            row.profile_id = record.profile_id
            row.classification = record.classification.value
            row.encrypted_response = record.encrypted_response
            row.expires_at = record.expires_at
        self._session.commit()
        return record

    @staticmethod
    def _cache_record(row: AICacheRow) -> AICacheRecord:
        return AICacheRecord(
            key=row.key,
            profile_id=row.profile_id,
            classification=DataClassification(row.classification),
            encrypted_response=row.encrypted_response,
            expires_at=row.expires_at,
            created_at=row.created_at,
        )
