from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from job_apply_pro.storage.database import Base


class WorkflowEventRow(Base):
    __tablename__ = "workflow_events"
    __table_args__ = (
        UniqueConstraint("workflow_id", "sequence", name="uq_workflow_event_sequence"),
        Index("ix_workflow_events_workflow_occurred", "workflow_id", "occurred_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(100), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    prior_state: Mapped[str] = mapped_column(String(40))
    next_state: Mapped[str] = mapped_column(String(40))
    actor: Mapped[str] = mapped_column(String(100))
    cause: Mapped[str] = mapped_column(Text)
    verification: Mapped[str] = mapped_column(String(20))
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CandidateProfileRow(Base):
    __tablename__ = "candidate_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200))
    encrypted_contact: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EvidenceSourceRow(Base):
    __tablename__ = "evidence_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    profile_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id"), index=True)
    document_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("document_versions.id"), nullable=True, index=True
    )
    source_type: Mapped[str] = mapped_column(String(60))
    source_label: Mapped[str] = mapped_column(String(255), default="Imported source")
    source_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CandidateClaimRow(Base):
    __tablename__ = "candidate_claims"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    profile_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id"), index=True)
    evidence_source_id: Mapped[str | None] = mapped_column(
        ForeignKey("evidence_sources.id"), nullable=True
    )
    canonical_key: Mapped[str] = mapped_column(String(160), index=True)
    statement: Mapped[str] = mapped_column(Text)
    claim_type: Mapped[str] = mapped_column(String(80))
    value_json: Mapped[dict[str, object]] = mapped_column(JSON)
    source_location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    context_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    confidence: Mapped[float] = mapped_column(Float)
    verification_status: Mapped[str] = mapped_column(String(20), index=True)
    permitted_use: Mapped[str] = mapped_column(String(30))
    sensitivity: Mapped[str] = mapped_column(String(20))
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    superseded_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("candidate_claims.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DocumentRow(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    profile_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    display_name: Mapped[str] = mapped_column(String(200))
    variant_label: Mapped[str] = mapped_column(String(120), default="General")
    job_family_tags_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DocumentVersionRow(Base):
    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "version", name="uq_document_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    file_name: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(100))
    sha256: Mapped[str] = mapped_column(String(64))
    storage_path: Mapped[str] = mapped_column(Text)
    encrypted_extraction: Mapped[str] = mapped_column(Text)
    parser_version: Mapped[str] = mapped_column(String(100))
    page_count: Mapped[int] = mapped_column(Integer)
    character_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class JobRow(Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_job_source_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source: Mapped[str] = mapped_column(String(80))
    external_id: Mapped[str] = mapped_column(String(200))
    employer: Mapped[str] = mapped_column(String(200), index=True)
    title: Mapped[str] = mapped_column(String(200))
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_hash: Mapped[str] = mapped_column(String(64))
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class JobRequirementRow(Base):
    __tablename__ = "job_requirements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    category: Mapped[str] = mapped_column(String(60))
    text: Mapped[str] = mapped_column(Text)
    required: Mapped[bool] = mapped_column(Boolean)
    evidence_json: Mapped[dict[str, object]] = mapped_column(JSON)


class FitScoreRow(Base):
    __tablename__ = "fit_scores"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    profile_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id"), index=True)
    score: Mapped[float] = mapped_column(Float)
    explanation_json: Mapped[dict[str, object]] = mapped_column(JSON)
    model_version: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ApplicationRow(Base):
    __tablename__ = "applications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    profile_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    state: Mapped[str] = mapped_column(String(40))
    selected_document_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("document_versions.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ApplicationAnswerRow(Base):
    __tablename__ = "application_answers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    canonical_field: Mapped[str] = mapped_column(String(60))
    encrypted_value: Mapped[str] = mapped_column(Text)
    provenance: Mapped[str] = mapped_column(String(200))
    confidence: Mapped[float] = mapped_column(Float)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AnswerLibraryRow(Base):
    __tablename__ = "answer_library"
    __table_args__ = (Index("ix_answer_library_profile_updated", "profile_id", "updated_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    profile_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id"), index=True)
    canonical_field: Mapped[str] = mapped_column(String(160), index=True)
    encrypted_question: Mapped[str] = mapped_column(Text)
    encrypted_answer: Mapped[str] = mapped_column(Text)
    evidence_claim_ids_json: Mapped[list[str]] = mapped_column(JSON)
    confidence: Mapped[float] = mapped_column(Float)
    approved: Mapped[bool] = mapped_column(Boolean)
    locked: Mapped[bool] = mapped_column(Boolean)
    reuse_permission: Mapped[str] = mapped_column(String(30))
    provenance_json: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RetrievalChunkRow(Base):
    __tablename__ = "retrieval_chunks"
    __table_args__ = (
        UniqueConstraint("source_type", "source_id", name="uq_retrieval_chunk_source"),
        Index("ix_retrieval_chunks_profile_source", "profile_id", "source_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    profile_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(30))
    source_id: Mapped[str] = mapped_column(String(36))
    canonical_key: Mapped[str] = mapped_column(String(160))
    encrypted_content: Mapped[str] = mapped_column(Text)
    token_hashes_json: Mapped[list[str]] = mapped_column(JSON)
    vector_json: Mapped[list[float]] = mapped_column(JSON)
    permitted_use: Mapped[str] = mapped_column(String(30))
    evidence_claim_ids_json: Mapped[list[str]] = mapped_column(JSON)
    provenance_json: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WorkflowCheckpointRow(Base):
    __tablename__ = "workflow_checkpoints"
    __table_args__ = (
        UniqueConstraint("workflow_id", "sequence", name="uq_workflow_checkpoint_sequence"),
        Index("ix_workflow_checkpoints_latest", "workflow_id", "sequence"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(100))
    sequence: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(40))
    page_fingerprint: Mapped[str] = mapped_column(String(200))
    encrypted_payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BrowserSessionRow(Base):
    __tablename__ = "browser_sessions"
    __table_args__ = (Index("ix_browser_sessions_workflow_updated", "workflow_id", "updated_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(100), index=True)
    engine: Mapped[str] = mapped_column(String(20))
    profile_name: Mapped[str] = mapped_column(String(80))
    user_data_dir: Mapped[str] = mapped_column(Text)
    artifact_dir: Mapped[str] = mapped_column(Text)
    headless: Mapped[bool] = mapped_column(Boolean)
    state: Mapped[str] = mapped_column(String(30), index=True)
    current_url: Mapped[str] = mapped_column(Text)
    allowed_origins_json: Mapped[list[str]] = mapped_column(JSON)
    last_observation_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    trace_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BrowserActionRow(Base):
    __tablename__ = "browser_actions"
    __table_args__ = (
        UniqueConstraint("session_id", "sequence", name="uq_browser_action_sequence"),
        Index("ix_browser_actions_session_created", "session_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("browser_sessions.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    action_json: Mapped[dict[str, object]] = mapped_column(JSON)
    verified: Mapped[bool] = mapped_column(Boolean)
    attempts: Mapped[int] = mapped_column(Integer)
    observation_json: Mapped[dict[str, object]] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ModelInvocationRow(Base):
    __tablename__ = "model_invocations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    profile_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    task_type: Mapped[str] = mapped_column(String(80))
    provider: Mapped[str] = mapped_column(String(80))
    model: Mapped[str] = mapped_column(String(120))
    prompt_version: Mapped[str] = mapped_column(String(80))
    schema_version: Mapped[str] = mapped_column(String(80))
    input_hash: Mapped[str] = mapped_column(String(64))
    cache_key: Mapped[str] = mapped_column(String(64), index=True)
    classification: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_micros: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    route_json: Mapped[list[str]] = mapped_column(JSON)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AICacheRow(Base):
    __tablename__ = "ai_cache"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    profile_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    classification: Mapped[str] = mapped_column(String(40))
    encrypted_response: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PortalRunRow(Base):
    __tablename__ = "portal_runs"
    __table_args__ = (Index("ix_portal_runs_workflow_updated", "workflow_id", "updated_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    portal: Mapped[str] = mapped_column(String(40))
    capabilities_json: Mapped[list[str]] = mapped_column(JSON)
    workflow_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    browser_session_id: Mapped[str] = mapped_column(ForeignKey("browser_sessions.id"), index=True)
    profile_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    state: Mapped[str] = mapped_column(String(40), index=True)
    portal_origin: Mapped[str] = mapped_column(Text)
    query: Mapped[str] = mapped_column(String(200))
    deduplicated: Mapped[bool] = mapped_column(Boolean)
    qualification_json: Mapped[dict[str, object]] = mapped_column(JSON)
    selected_document_version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id"))
    field_mappings_json: Mapped[list[dict[str, object]]] = mapped_column(JSON)
    review_fingerprint: Mapped[str] = mapped_column(String(200))
    submission_evidence_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    trace_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ChallengeSessionRow(Base):
    __tablename__ = "challenge_sessions"
    __table_args__ = (Index("ix_challenge_sessions_workflow_updated", "workflow_id", "updated_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(100), index=True)
    browser_session_id: Mapped[str] = mapped_column(ForeignKey("browser_sessions.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30), index=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    snapshot_json: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ChallengeEventRow(Base):
    __tablename__ = "challenge_events"
    __table_args__ = (
        UniqueConstraint("session_id", "sequence", name="uq_challenge_event_sequence"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("challenge_sessions.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(80))
    details_json: Mapped[dict[str, object]] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CommunicationRecordRow(Base):
    __tablename__ = "communication_records"
    __table_args__ = (
        UniqueConstraint(
            "provider", "provider_message_id", name="uq_communication_provider_message"
        ),
        Index("ix_communication_received", "received_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider: Mapped[str] = mapped_column(String(40), index=True)
    provider_message_id: Mapped[str] = mapped_column(String(500))
    provider_thread_id: Mapped[str] = mapped_column(String(500), index=True)
    category: Mapped[str] = mapped_column(String(50), index=True)
    workflow_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    requires_review: Mapped[bool] = mapped_column(Boolean)
    encrypted_analysis: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OAuthCredentialRow(Base):
    __tablename__ = "oauth_credentials"

    credential_reference: Mapped[str] = mapped_column(String(200), primary_key=True)
    provider: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    encrypted_token_set: Mapped[str] = mapped_column(Text)
    granted_scopes_json: Mapped[list[str]] = mapped_column(JSON)
    account_hint: Mapped[str | None] = mapped_column(String(200), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OAuthAuthorizationSessionRow(Base):
    __tablename__ = "oauth_authorization_sessions"

    state_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(40), index=True)
    client_id: Mapped[str] = mapped_column(String(500))
    redirect_uri: Mapped[str] = mapped_column(Text)
    requested_scopes_json: Mapped[list[str]] = mapped_column(JSON)
    encrypted_code_verifier: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OutboundDraftRow(Base):
    __tablename__ = "outbound_drafts"
    __table_args__ = (Index("ix_outbound_drafts_workflow_updated", "workflow_id", "updated_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("communication_records.id"), index=True)
    workflow_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(40))
    provider_thread_id: Mapped[str] = mapped_column(String(500))
    category: Mapped[str] = mapped_column(String(50))
    policy: Mapped[str] = mapped_column(String(30))
    document_version_ids_json: Mapped[list[str]] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    encrypted_payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CalendarMutationPlanRow(Base):
    __tablename__ = "calendar_mutation_plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider: Mapped[str] = mapped_column(String(40), index=True)
    workflow_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(40))
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    encrypted_payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CommunicationMutationAuditRow(Base):
    __tablename__ = "communication_mutation_audits"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_communication_mutation_idempotency"),
        Index("ix_communication_mutation_status_occurred", "status", "occurred_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))
    provider: Mapped[str] = mapped_column(String(40), index=True)
    resource_id: Mapped[str] = mapped_column(String(100), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200))
    fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), index=True)
    confirmed_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    provider_resource_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FollowUpRow(Base):
    __tablename__ = "communication_follow_ups"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_communication_follow_up_dedupe"),
        Index("ix_communication_follow_up_due", "status", "due_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(100), index=True)
    reason: Mapped[str] = mapped_column(String(500))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    channel: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(30), index=True)
    dedupe_key: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BackupManifestRow(Base):
    __tablename__ = "backup_manifests"
    __table_args__ = (Index("ix_backup_manifests_status_created", "status", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    archive_path: Mapped[str] = mapped_column(Text)
    archive_sha256: Mapped[str] = mapped_column(String(64))
    manifest_json: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BackupScheduleRow(Base):
    __tablename__ = "backup_schedules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    label: Mapped[str] = mapped_column(String(200))
    categories_json: Mapped[list[str]] = mapped_column(JSON)
    interval_hours: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, index=True)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RestorePlanRow(Base):
    __tablename__ = "restore_plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    backup_id: Mapped[str] = mapped_column(ForeignKey("backup_manifests.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    plan_json: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ErrorRecordRow(Base):
    __tablename__ = "error_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    classification: Mapped[str] = mapped_column(String(40))
    component: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(200))
    sanitized_context_json: Mapped[dict[str, object]] = mapped_column(JSON)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
