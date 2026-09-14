"""Explicit schema-0029 forward-restore policy; never reflect an untrusted database.

Source control review is required to admit a new table, column or schema revision.
The broad dependency set deliberately trades restore availability for preservation.
"""

from dataclasses import dataclass
from typing import Literal

from job_apply_pro.domain.ai import AITaskType, DataClassification
from job_apply_pro.domain.browser import BrowserActionKind, BrowserEngine, BrowserSessionState
from job_apply_pro.domain.challenges import ChallengeKind, ChallengeStatus
from job_apply_pro.domain.communications import IntegrationProvider
from job_apply_pro.domain.external_effects import ExternalEffectKind, ExternalEffectStatus
from job_apply_pro.domain.portals import (
    PortalKind,
    SupervisedPortalDisposition,
    SupervisedPortalRunState,
)
from job_apply_pro.domain.workflow import VerificationResult, WorkflowState


@dataclass(frozen=True)
class Column:
    name: str
    kind: Literal["text", "json", "integer", "boolean", "float", "datetime", "date"]
    nullable: bool
    limit: int = 8_388_608


@dataclass(frozen=True)
class Table:
    columns: tuple[Column, ...]
    key: tuple[str, ...]
    references: tuple[tuple[str, str, str], ...] = ()


@dataclass(frozen=True)
class Index:
    name: str
    columns: tuple[str, ...]


TABLES: dict[str, Table] = {
    "ai_cache": Table(
        (
            Column("key", "text", False, 64),
            Column("profile_id", "text", True, 36),
            Column("classification", "text", False, 40),
            Column("encrypted_response", "text", False),
            Column("expires_at", "datetime", False),
            Column("created_at", "datetime", False),
        ),
        ("key",),
        (),
    ),
    "ai_media_cleanup": Table(
        (
            Column("id", "text", False, 36),
            Column("provider_id", "text", False, 80),
            Column("account_fingerprint", "text", False, 64),
            Column("owner_token", "text", False, 80),
            Column("state", "text", False, 40),
            Column("encrypted_resource", "text", True),
            Column("attempts", "integer", False),
            Column("reason", "text", True, 80),
            Column("lease_until", "datetime", True),
            Column("next_attempt_at", "datetime", True),
            Column("created_at", "datetime", False),
            Column("updated_at", "datetime", False),
        ),
        ("id",),
        (),
    ),
    "answer_library": Table(
        (
            Column("id", "text", False, 36),
            Column("revision", "integer", False),
            Column("profile_id", "text", False, 36),
            Column("canonical_field", "text", False, 160),
            Column("encrypted_question", "text", False),
            Column("encrypted_answer", "text", False),
            Column("evidence_claim_ids_json", "json", False),
            Column("confidence", "float", False),
            Column("approved", "boolean", False),
            Column("locked", "boolean", False),
            Column("reuse_permission", "text", False, 30),
            Column("provenance_json", "json", False),
            Column("created_at", "datetime", False),
            Column("updated_at", "datetime", False),
        ),
        ("id",),
        (("profile_id", "candidate_profiles", "id"),),
    ),
    "answer_library_revisions": Table(
        (
            Column("id", "text", False, 36),
            Column("answer_id", "text", False, 36),
            Column("profile_id", "text", False, 36),
            Column("revision", "integer", False),
            Column("encrypted_question", "text", False),
            Column("canonical_field", "text", False, 160),
            Column("encrypted_answer", "text", False),
            Column("evidence_claim_ids_json", "json", False),
            Column("confidence", "float", False),
            Column("approved", "boolean", False),
            Column("locked", "boolean", False),
            Column("reuse_permission", "text", False, 30),
            Column("provenance_json", "json", False),
            Column("created_at", "datetime", False),
        ),
        ("id",),
        (("answer_id", "answer_library", "id"), ("profile_id", "candidate_profiles", "id")),
    ),
    "application_answers": Table(
        (
            Column("id", "text", False, 36),
            Column("application_id", "text", False, 36),
            Column("profile_id", "text", True, 36),
            Column("job_id", "text", True, 36),
            Column("revision", "integer", False),
            Column("encrypted_question", "text", True),
            Column("encrypted_normalized_question", "text", True),
            Column("canonical_field", "text", False, 160),
            Column("answer_kind", "text", False, 40),
            Column("validation_rules_json", "json", False),
            Column("encrypted_value", "text", False),
            Column("provenance", "text", False, 200),
            Column("status", "text", False, 40),
            Column("source_type", "text", False, 40),
            Column("source_answer_id", "text", True, 36),
            Column("library_answer_id", "text", True, 36),
            Column("evidence_claim_ids_json", "json", False),
            Column("retrieval_results_json", "json", False),
            Column("provider_id", "text", True, 80),
            Column("model_id", "text", True, 120),
            Column("prompt_version", "text", True, 40),
            Column("policy_version", "text", False, 40),
            Column("confidence", "float", False),
            Column("encrypted_generated_value", "text", True),
            Column("character_limit", "integer", False),
            Column("character_limit_applied", "boolean", False),
            Column("limitations_json", "json", False),
            Column("user_edited", "boolean", False),
            Column("reuse_permission", "text", False, 30),
            Column("approved", "boolean", False),
            Column("created_at", "datetime", False),
            Column("updated_at", "datetime", True),
        ),
        ("id",),
        (
            ("application_id", "applications", "id"),
            ("profile_id", "candidate_profiles", "id"),
            ("job_id", "jobs", "id"),
            ("library_answer_id", "answer_library", "id"),
        ),
    ),
    "application_field_bindings": Table(
        (
            Column("id", "text", False, 36),
            Column("application_id", "text", False, 36),
            Column("application_answer_id", "text", False, 36),
            Column("answer_revision", "integer", False),
            Column("portal", "text", False, 80),
            Column("page_fingerprint", "text", False, 200),
            Column("control_key", "text", False, 200),
            Column("control_kind", "text", False, 40),
            Column("encrypted_label", "text", False),
            Column("encrypted_options", "text", False),
            Column("required", "boolean", False),
            Column("canonical_field", "text", False, 160),
            Column("confidence", "float", False),
            Column("binding_source", "text", False, 40),
            Column("answer_source", "text", False, 40),
            Column("answer_kind", "text", False, 40),
            Column("validation_rules_json", "json", False),
            Column("automation_permission", "text", False, 40),
            Column("review_fingerprint", "text", False, 64),
            Column("created_at", "datetime", False),
            Column("updated_at", "datetime", False),
        ),
        ("id",),
        (
            ("application_id", "applications", "id"),
            ("application_answer_id", "application_answers", "id"),
        ),
    ),
    "application_field_executions": Table(
        (
            Column("id", "text", False, 36),
            Column("binding_id", "text", False, 36),
            Column("application_id", "text", False, 36),
            Column("application_answer_id", "text", False, 36),
            Column("answer_revision", "integer", False),
            Column("supervised_run_id", "text", False, 36),
            Column("browser_session_id", "text", False, 36),
            Column("portal", "text", False, 80),
            Column("page_fingerprint_before", "text", False, 200),
            Column("page_fingerprint_after", "text", False, 200),
            Column("control_key", "text", False, 200),
            Column("action_kind", "text", False, 40),
            Column("verified", "boolean", False),
            Column("action_fingerprint", "text", False, 64),
            Column("error", "text", True),
            Column("created_at", "datetime", False),
        ),
        ("id",),
        (
            ("binding_id", "application_field_bindings", "id"),
            ("application_id", "applications", "id"),
            ("application_answer_id", "application_answers", "id"),
            ("supervised_run_id", "supervised_portal_runs", "id"),
            ("browser_session_id", "browser_sessions", "id"),
        ),
    ),
    "applications": Table(
        (
            Column("id", "text", False, 36),
            Column("workflow_id", "text", False, 100),
            Column("profile_id", "text", False, 36),
            Column("job_id", "text", False, 36),
            Column("state", "text", False, 40),
            Column("selected_document_version_id", "text", True, 36),
            Column("created_at", "datetime", False),
            Column("updated_at", "datetime", False),
        ),
        ("id",),
        (
            ("profile_id", "candidate_profiles", "id"),
            ("job_id", "jobs", "id"),
            ("selected_document_version_id", "document_versions", "id"),
        ),
    ),
    "browser_actions": Table(
        (
            Column("id", "text", False, 36),
            Column("session_id", "text", False, 36),
            Column("sequence", "integer", False),
            Column("action_json", "json", False),
            Column("verified", "boolean", False),
            Column("attempts", "integer", False),
            Column("observation_json", "json", False),
            Column("error", "text", True),
            Column("created_at", "datetime", False),
        ),
        ("id",),
        (("session_id", "browser_sessions", "id"),),
    ),
    "browser_sessions": Table(
        (
            Column("id", "text", False, 36),
            Column("workflow_id", "text", False, 100),
            Column("engine", "text", False, 20),
            Column("profile_name", "text", False, 80),
            Column("user_data_dir", "text", False),
            Column("artifact_dir", "text", False),
            Column("headless", "boolean", False),
            Column("state", "text", False, 30),
            Column("current_url", "text", False),
            Column("allowed_origins_json", "json", False),
            Column("last_observation_json", "json", True),
            Column("trace_path", "text", True),
            Column("created_at", "datetime", False),
            Column("updated_at", "datetime", False),
        ),
        ("id",),
        (),
    ),
    "calendar_mutation_plans": Table(
        (
            Column("id", "text", False, 36),
            Column("provider", "text", False, 40),
            Column("workflow_id", "text", True, 100),
            Column("kind", "text", False, 40),
            Column("fingerprint", "text", False, 64),
            Column("encrypted_payload", "text", False),
            Column("created_at", "datetime", False),
        ),
        ("id",),
        (),
    ),
    "calendar_mutation_claims": Table(
        (
            Column("plan_id", "text", False, 36),
            Column("audit_id", "text", False, 36),
        ),
        ("plan_id",),
        (
            ("plan_id", "calendar_mutation_plans", "id"),
            ("audit_id", "communication_mutation_audits", "id"),
        ),
    ),
    "candidate_claims": Table(
        (
            Column("id", "text", False, 36),
            Column("profile_id", "text", False, 36),
            Column("evidence_source_id", "text", True, 36),
            Column("canonical_key", "text", False, 160),
            Column("statement", "text", False),
            Column("claim_type", "text", False, 80),
            Column("value_json", "json", False),
            Column("source_location", "text", True, 500),
            Column("context_json", "json", False),
            Column("start_date", "date", True),
            Column("end_date", "date", True),
            Column("confidence", "float", False),
            Column("verification_status", "text", False, 20),
            Column("permitted_use", "text", False, 30),
            Column("sensitivity", "text", False, 20),
            Column("locked", "boolean", False),
            Column("superseded_by_id", "text", True, 36),
            Column("created_at", "datetime", False),
            Column("updated_at", "datetime", False),
        ),
        ("id",),
        (
            ("profile_id", "candidate_profiles", "id"),
            ("evidence_source_id", "evidence_sources", "id"),
            ("superseded_by_id", "candidate_claims", "id"),
        ),
    ),
    "candidate_profiles": Table(
        (
            Column("id", "text", False, 36),
            Column("display_name", "text", False, 200),
            Column("encrypted_contact", "text", False),
            Column("status", "text", False, 20),
            Column("created_at", "datetime", False),
            Column("updated_at", "datetime", False),
        ),
        ("id",),
        (),
    ),
    "challenge_events": Table(
        (
            Column("id", "text", False, 36),
            Column("session_id", "text", False, 36),
            Column("sequence", "integer", False),
            Column("event_type", "text", False, 80),
            Column("details_json", "json", False),
            Column("occurred_at", "datetime", False),
        ),
        ("id",),
        (("session_id", "challenge_sessions", "id"),),
    ),
    "challenge_sessions": Table(
        (
            Column("id", "text", False, 36),
            Column("workflow_id", "text", False, 100),
            Column("browser_session_id", "text", False, 36),
            Column("kind", "text", False, 30),
            Column("status", "text", False, 40),
            Column("snapshot_json", "json", False),
            Column("created_at", "datetime", False),
            Column("updated_at", "datetime", False),
        ),
        ("id",),
        (("browser_session_id", "browser_sessions", "id"),),
    ),
    "communication_configurations": Table(
        (
            Column("id", "text", False, 20),
            Column("encrypted_configuration", "text", False),
            Column("updated_at", "datetime", False),
        ),
        ("id",),
        (),
    ),
    "communication_follow_ups": Table(
        (
            Column("id", "text", False, 36),
            Column("workflow_id", "text", False, 100),
            Column("reason", "text", False, 500),
            Column("due_at", "datetime", False),
            Column("channel", "text", False, 40),
            Column("status", "text", False, 30),
            Column("dedupe_key", "text", False, 64),
            Column("created_at", "datetime", False),
            Column("updated_at", "datetime", False),
        ),
        ("id",),
        (),
    ),
    "communication_mutation_audits": Table(
        (
            Column("id", "text", False, 36),
            Column("kind", "text", False, 40),
            Column("provider", "text", False, 40),
            Column("resource_id", "text", False, 100),
            Column("idempotency_key", "text", False, 200),
            Column("fingerprint", "text", False, 64),
            Column("status", "text", False, 30),
            Column("confirmed_by", "text", True, 200),
            Column("provider_resource_id", "text", True, 500),
            Column("error_code", "text", True, 100),
            Column("occurred_at", "datetime", False),
        ),
        ("id",),
        (),
    ),
    "communication_records": Table(
        (
            Column("id", "text", False, 36),
            Column("provider", "text", False, 40),
            Column("provider_message_id", "text", False, 500),
            Column("source_account_key", "text", False, 64),
            Column("source_connection_fingerprint", "text", False, 64),
            Column("provider_thread_id", "text", False, 500),
            Column("category", "text", False, 50),
            Column("workflow_id", "text", True, 100),
            Column("requires_review", "boolean", False),
            Column("encrypted_analysis", "text", False),
            Column("received_at", "datetime", False),
            Column("created_at", "datetime", False),
        ),
        ("id",),
        (),
    ),
    "document_generation_audits": Table(
        (
            Column("id", "text", False, 36),
            Column("application_id", "text", False, 36),
            Column("profile_id", "text", False, 36),
            Column("job_id", "text", False, 36),
            Column("document_version_id", "text", False, 36),
            Column("kind", "text", False, 30),
            Column("output_format", "text", False, 20),
            Column("template", "text", False, 30),
            Column("ranking_mode", "text", False, 30),
            Column("ranking_method", "text", False, 80),
            Column("review_fingerprint", "text", False, 64),
            Column("evidence_claim_ids_json", "json", False),
            Column("requirement_ids_json", "json", False),
            Column("missing_required_requirements_json", "json", False),
            Column("created_at", "datetime", False),
        ),
        ("id",),
        (
            ("application_id", "applications", "id"),
            ("profile_id", "candidate_profiles", "id"),
            ("job_id", "jobs", "id"),
            ("document_version_id", "document_versions", "id"),
        ),
    ),
    "document_selection_audits": Table(
        (
            Column("id", "text", False, 36),
            Column("application_id", "text", False, 36),
            Column("profile_id", "text", False, 36),
            Column("job_id", "text", False, 36),
            Column("document_id", "text", False, 36),
            Column("document_version_id", "text", False, 36),
            Column("score", "float", False),
            Column("review_fingerprint", "text", False, 64),
            Column("criteria_json", "json", False),
            Column("reasons_json", "json", False),
            Column("created_at", "datetime", False),
        ),
        ("id",),
        (
            ("application_id", "applications", "id"),
            ("profile_id", "candidate_profiles", "id"),
            ("job_id", "jobs", "id"),
            ("document_id", "documents", "id"),
            ("document_version_id", "document_versions", "id"),
        ),
    ),
    "document_versions": Table(
        (
            Column("id", "text", False, 36),
            Column("document_id", "text", False, 36),
            Column("version", "integer", False),
            Column("file_name", "text", False, 255),
            Column("media_type", "text", False, 100),
            Column("sha256", "text", False, 64),
            Column("storage_path", "text", False),
            Column("encrypted_extraction", "text", False),
            Column("parser_version", "text", False, 100),
            Column("page_count", "integer", False),
            Column("character_count", "integer", False),
            Column("created_at", "datetime", False),
        ),
        ("id",),
        (("document_id", "documents", "id"),),
    ),
    "documents": Table(
        (
            Column("id", "text", False, 36),
            Column("profile_id", "text", False, 36),
            Column("kind", "text", False, 30),
            Column("display_name", "text", False, 200),
            Column("variant_label", "text", False, 120),
            Column("job_family_tags_json", "json", False),
            Column("is_primary", "boolean", False),
            Column("archived", "boolean", False),
            Column("created_at", "datetime", False),
        ),
        ("id",),
        (("profile_id", "candidate_profiles", "id"),),
    ),
    "evidence_sources": Table(
        (
            Column("id", "text", False, 36),
            Column("profile_id", "text", False, 36),
            Column("document_version_id", "text", True, 36),
            Column("source_type", "text", False, 60),
            Column("source_label", "text", False, 255),
            Column("source_uri", "text", True),
            Column("content_hash", "text", False, 64),
            Column("created_at", "datetime", False),
        ),
        ("id",),
        (
            ("profile_id", "candidate_profiles", "id"),
            ("document_version_id", "document_versions", "id"),
        ),
    ),
    "external_effect_attempts": Table(
        (
            Column("id", "text", False, 36),
            Column("operation_id", "text", False, 36),
            Column("sequence", "integer", False),
            Column("provider", "text", False, 200),
            Column("target_code", "text", False, 200),
            Column("request_fingerprint", "text", False, 64),
            Column("native_key_fingerprint", "text", True, 64),
            Column("status", "text", False, 20),
            Column("result_reference", "text", True, 200),
            Column("result_fingerprint", "text", True, 64),
            Column("error_code", "text", True, 80),
            Column("input_tokens", "integer", True),
            Column("output_tokens", "integer", True),
            Column("cost_micros", "integer", True),
            Column("created_at", "datetime", False),
            Column("updated_at", "datetime", False),
            Column("completed_at", "datetime", True),
        ),
        ("id",),
        (("operation_id", "external_effect_operations", "id"),),
    ),
    "external_effect_operations": Table(
        (
            Column("id", "text", False, 36),
            Column("claim_fingerprint", "text", False, 64),
            Column("kind", "text", False, 40),
            Column("subject_type", "text", False, 40),
            Column("subject_id", "text", False, 200),
            Column("actor", "text", False, 200),
            Column("request_fingerprint", "text", False, 64),
            Column("policy_version", "text", False, 200),
            Column("status", "text", False, 20),
            Column("result_reference", "text", True, 200),
            Column("result_fingerprint", "text", True, 64),
            Column("error_code", "text", True, 80),
            Column("created_at", "datetime", False),
            Column("updated_at", "datetime", False),
            Column("completed_at", "datetime", True),
        ),
        ("id",),
        (),
    ),
    "fit_scores": Table(
        (
            Column("id", "text", False, 36),
            Column("job_id", "text", False, 36),
            Column("profile_id", "text", False, 36),
            Column("score", "float", False),
            Column("explanation_json", "json", False),
            Column("model_version", "text", False, 100),
            Column("created_at", "datetime", False),
        ),
        ("id",),
        (("job_id", "jobs", "id"), ("profile_id", "candidate_profiles", "id")),
    ),
    "job_discovery_snapshots": Table(
        (
            Column("job_id", "text", False, 36),
            Column("review_fingerprint", "text", False, 64),
            Column("review_json", "json", False),
            Column("created_at", "datetime", False),
        ),
        ("job_id",),
        (("job_id", "jobs", "id"),),
    ),
    "job_readiness_reviews": Table(
        (
            Column("id", "text", False, 36),
            Column("application_id", "text", False, 36),
            Column("kind", "text", False, 20),
            Column("revision", "integer", False),
            Column("request_fingerprint", "text", False, 64),
            Column("encrypted_payload", "text", False),
            Column("created_at", "datetime", False),
        ),
        ("id",),
        (("application_id", "applications", "id"),),
    ),
    "job_requirements": Table(
        (
            Column("id", "text", False, 36),
            Column("job_id", "text", False, 36),
            Column("category", "text", False, 60),
            Column("text", "text", False),
            Column("required", "boolean", False),
            Column("evidence_json", "json", False),
        ),
        ("id",),
        (("job_id", "jobs", "id"),),
    ),
    "jobs": Table(
        (
            Column("id", "text", False, 36),
            Column("source", "text", False, 80),
            Column("external_id", "text", False, 200),
            Column("employer", "text", False, 200),
            Column("title", "text", False, 200),
            Column("location", "text", True, 200),
            Column("source_url", "text", True),
            Column("description_hash", "text", False, 64),
            Column("discovered_at", "datetime", False),
        ),
        ("id",),
        (),
    ),
    "mail_send_claims": Table(
        (
            Column("draft_id", "text", False, 36),
            Column("audit_id", "text", False, 36),
        ),
        ("draft_id",),
        (
            ("draft_id", "outbound_drafts", "id"),
            ("audit_id", "communication_mutation_audits", "id"),
        ),
    ),
    "model_invocations": Table(
        (
            Column("id", "text", False, 36),
            Column("profile_id", "text", True, 36),
            Column("task_type", "text", False, 80),
            Column("provider", "text", False, 80),
            Column("model", "text", False, 120),
            Column("prompt_version", "text", False, 80),
            Column("schema_version", "text", False, 80),
            Column("input_hash", "text", False, 64),
            Column("cache_key", "text", False, 64),
            Column("classification", "text", False, 40),
            Column("status", "text", False, 20),
            Column("input_tokens", "integer", False),
            Column("output_tokens", "integer", False),
            Column("cost_micros", "integer", False),
            Column("attempts", "integer", False),
            Column("route_json", "json", False),
            Column("latency_ms", "integer", False),
            Column("error_code", "text", True, 80),
            Column("created_at", "datetime", False),
            Column("completed_at", "datetime", False),
        ),
        ("id",),
        (),
    ),
    "oauth_authorization_sessions": Table(
        (
            Column("state_hash", "text", False, 64),
            Column("provider", "text", False, 40),
            Column("client_id", "text", False, 500),
            Column("redirect_uri", "text", False),
            Column("requested_scopes_json", "json", False),
            Column("encrypted_code_verifier", "text", False),
            Column("expires_at", "datetime", False),
            Column("consumed_at", "datetime", True),
        ),
        ("state_hash",),
        (),
    ),
    "oauth_credentials": Table(
        (
            Column("credential_reference", "text", False, 200),
            Column("provider", "text", False, 40),
            Column("encrypted_token_set", "text", False),
            Column("granted_scopes_json", "json", False),
            Column("account_hint", "text", True, 200),
            Column("expires_at", "datetime", False),
            Column("updated_at", "datetime", False),
        ),
        ("credential_reference",),
        (),
    ),
    "outbound_drafts": Table(
        (
            Column("id", "text", False, 36),
            Column("analysis_id", "text", False, 36),
            Column("workflow_id", "text", True, 100),
            Column("provider", "text", False, 40),
            Column("provider_thread_id", "text", False, 500),
            Column("category", "text", False, 50),
            Column("policy", "text", False, 30),
            Column("document_version_ids_json", "json", False),
            Column("fingerprint", "text", False, 64),
            Column("encrypted_payload", "text", False),
            Column("created_at", "datetime", False),
            Column("updated_at", "datetime", False),
        ),
        ("id",),
        (("analysis_id", "communication_records", "id"),),
    ),
    "portal_runs": Table(
        (
            Column("id", "text", False, 36),
            Column("portal", "text", False, 40),
            Column("capabilities_json", "json", False),
            Column("workflow_id", "text", False, 100),
            Column("application_id", "text", False, 36),
            Column("browser_session_id", "text", False, 36),
            Column("profile_id", "text", False, 36),
            Column("job_id", "text", False, 36),
            Column("state", "text", False, 40),
            Column("portal_origin", "text", False),
            Column("query", "text", False, 200),
            Column("deduplicated", "boolean", False),
            Column("qualification_json", "json", False),
            Column("selected_document_version_id", "text", False, 36),
            Column("field_mappings_json", "json", False),
            Column("review_fingerprint", "text", False, 200),
            Column("submission_evidence_json", "json", True),
            Column("trace_path", "text", True),
            Column("created_at", "datetime", False),
            Column("updated_at", "datetime", False),
        ),
        ("id",),
        (
            ("application_id", "applications", "id"),
            ("browser_session_id", "browser_sessions", "id"),
            ("profile_id", "candidate_profiles", "id"),
            ("job_id", "jobs", "id"),
            ("selected_document_version_id", "document_versions", "id"),
        ),
    ),
    "provider_calendar_events": Table(
        (
            Column("id", "text", False, 36),
            Column("provider", "text", False, 40),
            Column("event_fingerprint", "text", False, 64),
            Column("binding_fingerprint", "text", False, 64),
            Column("starts_at", "datetime", False),
            Column("ends_at", "datetime", False),
            Column("encrypted_event", "text", False),
            Column("synced_at", "datetime", False),
        ),
        ("id",),
        (),
    ),
    "provider_sync_states": Table(
        (
            Column("provider", "text", False, 40),
            Column("encrypted_cursor", "text", False),
            Column("updated_at", "datetime", False),
        ),
        ("provider",),
        (),
    ),
    "retrieval_chunks": Table(
        (
            Column("id", "text", False, 36),
            Column("profile_id", "text", False, 36),
            Column("source_type", "text", False, 30),
            Column("source_id", "text", False, 36),
            Column("canonical_key", "text", False, 160),
            Column("encrypted_content", "text", False),
            Column("token_hashes_json", "json", False),
            Column("vector_json", "json", False),
            Column("permitted_use", "text", False, 30),
            Column("evidence_claim_ids_json", "json", False),
            Column("provenance_json", "json", False),
            Column("created_at", "datetime", False),
            Column("updated_at", "datetime", False),
        ),
        ("id",),
        (("profile_id", "candidate_profiles", "id"),),
    ),
    "submitted_document_evidence": Table(
        (
            Column("id", "text", False, 36),
            Column("application_id", "text", False, 36),
            Column("document_version_id", "text", False, 36),
            Column("role", "text", False, 30),
            Column("file_name", "text", False, 255),
            Column("sha256", "text", False, 64),
            Column("upload_fingerprint", "text", False, 200),
            Column("captured_at", "datetime", False),
        ),
        ("id",),
        (
            ("application_id", "applications", "id"),
            ("document_version_id", "document_versions", "id"),
        ),
    ),
    "supervised_portal_runs": Table(
        (
            Column("id", "text", False, 36),
            Column("portal", "text", False, 40),
            Column("workflow_id", "text", False, 100),
            Column("browser_session_id", "text", False, 36),
            Column("state", "text", False, 40),
            Column("current_url", "text", False),
            Column("allowed_origins_json", "json", False),
            Column("page_fingerprint", "text", False, 200),
            Column("current_match_json", "json", True),
            Column("disposition", "text", False, 50),
            Column("intervention_reasons_json", "json", False),
            Column("trace_path", "text", True),
            Column("created_at", "datetime", False),
            Column("updated_at", "datetime", False),
        ),
        ("id",),
        (("browser_session_id", "browser_sessions", "id"),),
    ),
    "supervised_portal_step_evidence": Table(
        (
            Column("id", "text", False, 36),
            Column("run_id", "text", False, 36),
            Column("sequence", "integer", False),
            Column("disposition", "text", False, 50),
            Column("capability", "text", True, 40),
            Column("page_type", "text", False, 100),
            Column("before_fingerprint", "text", False, 200),
            Column("after_fingerprint", "text", False, 200),
            Column("action_kind", "text", True, 40),
            Column("action_fingerprint", "text", False, 64),
            Column("verified", "boolean", False),
            Column("intervention_reasons_json", "json", False),
            Column("created_at", "datetime", False),
        ),
        ("id",),
        (("run_id", "supervised_portal_runs", "id"),),
    ),
    "workflow_checkpoints": Table(
        (
            Column("id", "text", False, 36),
            Column("workflow_id", "text", False, 100),
            Column("sequence", "integer", False),
            Column("state", "text", False, 40),
            Column("page_fingerprint", "text", False, 200),
            Column("encrypted_payload", "text", False),
            Column("created_at", "datetime", False),
        ),
        ("id",),
        (),
    ),
    "workflow_events": Table(
        (
            Column("id", "text", False, 36),
            Column("workflow_id", "text", False, 100),
            Column("sequence", "integer", False),
            Column("prior_state", "text", False, 40),
            Column("next_state", "text", False, 40),
            Column("actor", "text", False, 100),
            Column("cause", "text", False),
            Column("verification", "text", False, 20),
            Column("retry_count", "integer", False),
            Column("occurred_at", "datetime", False),
        ),
        ("id",),
        (),
    ),
}

# Every current row in these domains is preserved once either database records
# any external/replay root. This intentionally includes unrelated local changes.
ROOTS = frozenset(
    {
        "communication_mutation_audits",
        "mail_send_claims",
        "calendar_mutation_claims",
        "calendar_mutation_plans",
        "oauth_credentials",
        "oauth_authorization_sessions",
        "communication_configurations",
        "browser_sessions",
        "browser_actions",
        "portal_runs",
        "supervised_portal_runs",
        "supervised_portal_step_evidence",
        "application_field_executions",
        "submitted_document_evidence",
        "challenge_sessions",
        "challenge_events",
        "model_invocations",
        "ai_media_cleanup",
        "external_effect_operations",
        "external_effect_attempts",
    }
)

# A restored-only mutable authority/session/cache can revive revoked authority
# or stale resumable state. Do not infer that it is safe from expiry/status.
EXACT_SETS = frozenset(
    {
        "oauth_credentials",
        "oauth_authorization_sessions",
        "communication_configurations",
        "browser_sessions",
        "portal_runs",
        "supervised_portal_runs",
        "challenge_sessions",
        "provider_sync_states",
        "provider_calendar_events",
        "ai_cache",
        "external_effect_operations",
        "external_effect_attempts",
    }
)

# These mutable snapshots also trigger admission when there is no mutation audit.
ROOTS = ROOTS | EXACT_SETS

MODERN_REVISION = "20260913_0029"
OPERATIONAL_TABLES = frozenset(
    {"alembic_version", "backup_manifests", "backup_schedules", "restore_plans", "error_records"}
)

# Only compiled, supported history-state values are interpretable. Opaque prose,
# provider IDs for model adapters, and event names remain exact retained values.
ENUM_FIELDS: dict[tuple[str, str], frozenset[str]] = {
    ("browser_sessions", "engine"): frozenset(BrowserEngine),
    ("browser_sessions", "state"): frozenset(BrowserSessionState),
    ("portal_runs", "state"): frozenset(WorkflowState),
    ("supervised_portal_runs", "state"): frozenset(SupervisedPortalRunState),
    ("supervised_portal_runs", "disposition"): frozenset(SupervisedPortalDisposition),
    ("supervised_portal_step_evidence", "disposition"): frozenset(SupervisedPortalDisposition),
    ("challenge_sessions", "kind"): frozenset(ChallengeKind),
    ("challenge_sessions", "status"): frozenset(ChallengeStatus),
    ("application_field_executions", "action_kind"): frozenset(BrowserActionKind),
    ("supervised_portal_step_evidence", "action_kind"): frozenset(BrowserActionKind),
    ("model_invocations", "task_type"): frozenset(AITaskType),
    ("model_invocations", "classification"): frozenset(DataClassification),
    ("ai_cache", "classification"): frozenset(DataClassification),
    ("external_effect_operations", "kind"): frozenset(ExternalEffectKind),
    ("external_effect_operations", "status"): frozenset(ExternalEffectStatus),
    ("external_effect_attempts", "status"): frozenset(ExternalEffectStatus),
    ("calendar_mutation_plans", "kind"): frozenset(
        {"CREATE_CALENDAR_EVENT", "UPDATE_CALENDAR_EVENT"}
    ),
    ("applications", "state"): frozenset(WorkflowState),
    ("workflow_events", "prior_state"): frozenset(WorkflowState),
    ("workflow_events", "next_state"): frozenset(WorkflowState),
    ("workflow_events", "verification"): frozenset(VerificationResult),
}
ENUM_FIELDS.update(
    {
        (table, "portal"): frozenset(PortalKind)
        for table in (
            "portal_runs",
            "supervised_portal_runs",
            "application_field_bindings",
            "application_field_executions",
        )
    }
)
ENUM_FIELDS.update(
    {
        (table, "provider"): frozenset(IntegrationProvider)
        for table in (
            "communication_records",
            "outbound_drafts",
            "calendar_mutation_plans",
            "communication_mutation_audits",
            "oauth_credentials",
            "oauth_authorization_sessions",
            "provider_sync_states",
            "provider_calendar_events",
        )
    }
)
# Only these complete near-modern shapes are admitted without recorded history.
# Older, unversioned or unknown schemas need an independently reviewed recovery path.
LEGACY_EMPTY_REVISIONS = {
    "20260913_0025": frozenset(
        {
            "job_readiness_reviews",
            "calendar_mutation_claims",
            "external_effect_operations",
            "external_effect_attempts",
        }
    ),
    "20260913_0026": frozenset(
        {
            "job_readiness_reviews",
            "calendar_mutation_claims",
            "external_effect_operations",
            "external_effect_attempts",
        }
    ),
    "20260913_0027": frozenset(
        {
            "calendar_mutation_claims",
            "external_effect_operations",
            "external_effect_attempts",
        }
    ),
    "20260913_0028": frozenset({"external_effect_operations", "external_effect_attempts"}),
}

# SQL uniqueness is checked explicitly even when a corrupted database lost its constraints.
UNIQUES: dict[str, tuple[tuple[str, ...], ...]] = {
    "workflow_events": (("workflow_id", "sequence"),),
    "document_versions": (("document_id", "version"),),
    "document_generation_audits": (("document_version_id",),),
    "jobs": (("source", "external_id"),),
    "job_readiness_reviews": (
        ("application_id", "kind", "revision"),
        ("application_id", "kind", "request_fingerprint"),
    ),
    "applications": (("workflow_id",),),
    "application_field_bindings": (("application_id", "page_fingerprint", "control_key"),),
    "submitted_document_evidence": (
        ("application_id", "document_version_id", "role", "upload_fingerprint"),
    ),
    "answer_library_revisions": (("answer_id", "revision"),),
    "retrieval_chunks": (("source_type", "source_id"),),
    "workflow_checkpoints": (("workflow_id", "sequence"),),
    "browser_actions": (("session_id", "sequence"),),
    "portal_runs": (("workflow_id",),),
    "supervised_portal_runs": (("browser_session_id",),),
    "supervised_portal_step_evidence": (("run_id", "sequence"),),
    "challenge_events": (("session_id", "sequence"),),
    "communication_records": (
        ("provider", "source_account_key", "source_connection_fingerprint", "provider_message_id"),
    ),
    "provider_calendar_events": (("provider", "event_fingerprint"),),
    "oauth_credentials": (("provider",),),
    "communication_mutation_audits": (("idempotency_key",),),
    "mail_send_claims": (("audit_id",),),
    "calendar_mutation_claims": (("audit_id",),),
    "communication_follow_ups": (("dedupe_key",),),
    "external_effect_operations": (("claim_fingerprint",),),
    "external_effect_attempts": (("operation_id", "sequence"),),
}

# SQLite declarations are part of restore compatibility. ``None`` is the
# create-all form; the other reviewed defaults are residues from additive
# migrations and remain valid in databases upgraded through Alembic.
MIGRATION_DEFAULTS: dict[tuple[str, str], frozenset[str | None]] = {
    ("answer_library", "revision"): frozenset((None, "'1'")),
    ("application_answers", "revision"): frozenset((None, "'1'")),
    ("application_answers", "status"): frozenset((None, "'LEGACY_REVIEW_REQUIRED'")),
    ("application_answers", "source_type"): frozenset((None, "'LEGACY'")),
    ("application_answers", "evidence_claim_ids_json"): frozenset((None, "'[]'")),
    ("application_answers", "retrieval_results_json"): frozenset((None, "'[]'")),
    ("application_answers", "policy_version"): frozenset((None, "'answer-drafting/1.0'")),
    ("application_answers", "character_limit"): frozenset((None, "'20000'")),
    ("application_answers", "character_limit_applied"): frozenset((None, "0")),
    ("application_answers", "limitations_json"): frozenset((None, "'[]'")),
    ("application_answers", "user_edited"): frozenset((None, "0")),
    ("application_answers", "reuse_permission"): frozenset((None, "'APPLICATIONS'")),
    ("application_answers", "answer_kind"): frozenset((None, "'SHORT_TEXT'")),
    ("application_answers", "validation_rules_json"): frozenset((None, "'{}'")),
    ("application_field_bindings", "required"): frozenset((None, "0")),
    ("application_field_bindings", "validation_rules_json"): frozenset((None, "'{}'")),
    ("candidate_claims", "canonical_key"): frozenset((None, "'legacy'")),
    ("candidate_claims", "statement"): frozenset((None, "'Legacy claim'")),
    ("candidate_claims", "context_json"): frozenset((None, "'{}'")),
    ("candidate_claims", "verification_status"): frozenset((None, "'PROPOSED'")),
    ("candidate_claims", "permitted_use"): frozenset((None, "'PROFILE_ONLY'")),
    ("candidate_claims", "sensitivity"): frozenset((None, "'PERSONAL'")),
    ("candidate_claims", "updated_at"): frozenset((None, "CURRENT_TIMESTAMP")),
    ("communication_records", "source_account_key"): frozenset(
        (None, "'0000000000000000000000000000000000000000000000000000000000000000'")
    ),
    ("communication_records", "source_connection_fingerprint"): frozenset(
        (None, "'0000000000000000000000000000000000000000000000000000000000000000'")
    ),
    ("document_generation_audits", "template"): frozenset((None, "'PROFESSIONAL'")),
    ("document_generation_audits", "ranking_mode"): frozenset((None, "'DETERMINISTIC'")),
    ("document_generation_audits", "ranking_method"): frozenset(
        (None, "'DETERMINISTIC_TOKEN_OVERLAP'")
    ),
    ("document_versions", "encrypted_extraction"): frozenset((None, "''")),
    ("document_versions", "parser_version"): frozenset((None, "'legacy'")),
    ("document_versions", "page_count"): frozenset((None, "'1'")),
    ("document_versions", "character_count"): frozenset((None, "'0'")),
    ("documents", "variant_label"): frozenset((None, "'General'")),
    ("documents", "job_family_tags_json"): frozenset((None, "'[]'")),
    ("documents", "is_primary"): frozenset((None, "0")),
    ("documents", "archived"): frozenset((None, "0")),
    ("evidence_sources", "source_label"): frozenset((None, "'Imported source'")),
    ("model_invocations", "cache_key"): frozenset((None, "''")),
    ("model_invocations", "classification"): frozenset((None, "'ROUTINE'")),
    ("model_invocations", "attempts"): frozenset((None, "'0'")),
    ("model_invocations", "route_json"): frozenset((None, "'[]'")),
    ("model_invocations", "latency_ms"): frozenset((None, "'0'")),
    ("model_invocations", "completed_at"): frozenset((None, "CURRENT_TIMESTAMP")),
}


def sqlite_declaration(column: Column) -> str:
    """Return the reviewed SQLite declaration for a protected column."""
    if column.kind == "text":
        return f"VARCHAR({column.limit})" if column.limit < 8_388_608 else "TEXT"
    return {
        "json": "JSON",
        "integer": "INTEGER",
        "boolean": "BOOLEAN",
        "float": "FLOAT",
        "datetime": "DATETIME",
        "date": "DATE",
    }[column.kind]


# Named indexes are checked in addition to effective UNIQUE constraints. The
# latter may be represented by either a named unique index (fresh ORM test
# databases) or a table constraint plus a same-column lookup index (Alembic).
INDEXES: dict[str, tuple[Index, ...]] = {
    "ai_cache": (
        Index("ix_ai_cache_expires_at", ("expires_at",)),
        Index("ix_ai_cache_profile_id", ("profile_id",)),
    ),
    "ai_media_cleanup": (
        Index("ix_ai_media_cleanup_account", ("account_fingerprint", "state", "provider_id")),
        Index("ix_ai_media_cleanup_recovery", ("state", "lease_until", "next_attempt_at")),
    ),
    "answer_library": (
        Index("ix_answer_library_canonical_field", ("canonical_field",)),
        Index("ix_answer_library_profile_id", ("profile_id",)),
        Index("ix_answer_library_profile_updated", ("profile_id", "updated_at")),
    ),
    "answer_library_revisions": (
        Index("ix_answer_library_revisions_answer_created", ("answer_id", "created_at")),
        Index("ix_answer_library_revisions_answer_id", ("answer_id",)),
        Index("ix_answer_library_revisions_profile_id", ("profile_id",)),
    ),
    "application_answers": (
        Index("ix_application_answers_application_id", ("application_id",)),
        Index("ix_application_answers_job_id", ("job_id",)),
        Index("ix_application_answers_profile_id", ("profile_id",)),
    ),
    "application_field_bindings": (
        Index("ix_application_field_bindings_application_answer_id", ("application_answer_id",)),
        Index(
            "ix_application_field_bindings_application_created",
            ("application_id", "created_at"),
        ),
        Index("ix_application_field_bindings_application_id", ("application_id",)),
    ),
    "application_field_executions": (
        Index(
            "ix_application_field_executions_application_answer_id",
            ("application_answer_id",),
        ),
        Index(
            "ix_application_field_executions_application_created",
            ("application_id", "created_at"),
        ),
        Index("ix_application_field_executions_application_id", ("application_id",)),
        Index("ix_application_field_executions_binding_id", ("binding_id",)),
        Index("ix_application_field_executions_browser_session_id", ("browser_session_id",)),
        Index("ix_application_field_executions_supervised_run_id", ("supervised_run_id",)),
    ),
    "applications": (
        Index("ix_applications_job_id", ("job_id",)),
        Index("ix_applications_profile_id", ("profile_id",)),
        Index("ix_applications_workflow_id", ("workflow_id",)),
    ),
    "browser_actions": (
        Index("ix_browser_actions_session_created", ("session_id", "created_at")),
        Index("ix_browser_actions_session_id", ("session_id",)),
    ),
    "browser_sessions": (
        Index("ix_browser_sessions_state", ("state",)),
        Index("ix_browser_sessions_workflow_id", ("workflow_id",)),
        Index("ix_browser_sessions_workflow_updated", ("workflow_id", "updated_at")),
    ),
    "calendar_mutation_plans": (
        Index("ix_calendar_mutation_plans_fingerprint", ("fingerprint",)),
        Index("ix_calendar_mutation_plans_provider", ("provider",)),
        Index("ix_calendar_mutation_plans_workflow_id", ("workflow_id",)),
    ),
    "candidate_claims": (
        Index("ix_candidate_claims_canonical_key", ("canonical_key",)),
        Index("ix_candidate_claims_profile_id", ("profile_id",)),
        Index("ix_candidate_claims_verification_status", ("verification_status",)),
    ),
    "candidate_profiles": (Index("ix_candidate_profiles_status", ("status",)),),
    "challenge_events": (Index("ix_challenge_events_session_id", ("session_id",)),),
    "challenge_sessions": (
        Index("ix_challenge_sessions_browser_session_id", ("browser_session_id",)),
        Index("ix_challenge_sessions_kind", ("kind",)),
        Index("ix_challenge_sessions_status", ("status",)),
        Index("ix_challenge_sessions_workflow_id", ("workflow_id",)),
        Index("ix_challenge_sessions_workflow_updated", ("workflow_id", "updated_at")),
    ),
    "communication_follow_ups": (
        Index("ix_communication_follow_up_due", ("status", "due_at")),
        Index("ix_communication_follow_ups_status", ("status",)),
        Index("ix_communication_follow_ups_workflow_id", ("workflow_id",)),
    ),
    "communication_mutation_audits": (
        Index("ix_communication_mutation_audits_provider", ("provider",)),
        Index("ix_communication_mutation_audits_resource_id", ("resource_id",)),
        Index("ix_communication_mutation_audits_status", ("status",)),
        Index("ix_communication_mutation_status_occurred", ("status", "occurred_at")),
    ),
    "communication_records": (
        Index("ix_communication_received", ("received_at",)),
        Index("ix_communication_records_category", ("category",)),
        Index("ix_communication_records_provider", ("provider",)),
        Index("ix_communication_records_provider_thread_id", ("provider_thread_id",)),
        Index("ix_communication_records_workflow_id", ("workflow_id",)),
    ),
    "document_generation_audits": (
        Index("ix_document_generation_audits_application_id", ("application_id",)),
        Index("ix_document_generation_audits_document_version_id", ("document_version_id",)),
        Index("ix_document_generation_audits_job_id", ("job_id",)),
        Index("ix_document_generation_audits_profile_id", ("profile_id",)),
    ),
    "document_selection_audits": (
        Index("ix_document_selection_audits_application_id", ("application_id",)),
        Index("ix_document_selection_audits_job_id", ("job_id",)),
        Index("ix_document_selection_audits_profile_id", ("profile_id",)),
    ),
    "document_versions": (Index("ix_document_versions_document_id", ("document_id",)),),
    "documents": (Index("ix_documents_profile_id", ("profile_id",)),),
    "evidence_sources": (
        Index("ix_evidence_sources_document_version_id", ("document_version_id",)),
        Index("ix_evidence_sources_profile_id", ("profile_id",)),
    ),
    "external_effect_attempts": (
        Index("ix_external_effect_attempt_recovery", ("status", "updated_at")),
        Index("ix_external_effect_attempts_operation_id", ("operation_id",)),
        Index("ix_external_effect_attempts_status", ("status",)),
    ),
    "external_effect_operations": (
        Index("ix_external_effect_operation_recovery", ("status", "updated_at")),
        Index(
            "ix_external_effect_operation_subject",
            ("subject_type", "subject_id", "created_at"),
        ),
        Index("ix_external_effect_operations_kind", ("kind",)),
        Index("ix_external_effect_operations_status", ("status",)),
    ),
    "fit_scores": (
        Index("ix_fit_scores_job_id", ("job_id",)),
        Index("ix_fit_scores_profile_id", ("profile_id",)),
    ),
    "job_readiness_reviews": (
        Index("ix_job_readiness_reviews_application_id", ("application_id",)),
    ),
    "job_requirements": (Index("ix_job_requirements_job_id", ("job_id",)),),
    "jobs": (Index("ix_jobs_employer", ("employer",)),),
    "model_invocations": (
        Index("ix_model_invocations_cache_key", ("cache_key",)),
        Index("ix_model_invocations_profile_id", ("profile_id",)),
    ),
    "oauth_authorization_sessions": (
        Index("ix_oauth_authorization_sessions_expires_at", ("expires_at",)),
        Index("ix_oauth_authorization_sessions_provider", ("provider",)),
    ),
    "oauth_credentials": (Index("ix_oauth_credentials_provider", ("provider",)),),
    "outbound_drafts": (
        Index("ix_outbound_drafts_analysis_id", ("analysis_id",)),
        Index("ix_outbound_drafts_fingerprint", ("fingerprint",)),
        Index("ix_outbound_drafts_workflow_id", ("workflow_id",)),
        Index("ix_outbound_drafts_workflow_updated", ("workflow_id", "updated_at")),
    ),
    "portal_runs": (
        Index("ix_portal_runs_application_id", ("application_id",)),
        Index("ix_portal_runs_browser_session_id", ("browser_session_id",)),
        Index("ix_portal_runs_job_id", ("job_id",)),
        Index("ix_portal_runs_profile_id", ("profile_id",)),
        Index("ix_portal_runs_state", ("state",)),
        Index("ix_portal_runs_workflow_id", ("workflow_id",)),
        Index("ix_portal_runs_workflow_updated", ("workflow_id", "updated_at")),
    ),
    "provider_calendar_events": (
        Index("ix_provider_calendar_event_window", ("provider", "starts_at", "ends_at")),
        Index("ix_provider_calendar_events_binding_fingerprint", ("binding_fingerprint",)),
        Index("ix_provider_calendar_events_provider", ("provider",)),
    ),
    "retrieval_chunks": (
        Index("ix_retrieval_chunks_profile_id", ("profile_id",)),
        Index("ix_retrieval_chunks_profile_source", ("profile_id", "source_type")),
    ),
    "submitted_document_evidence": (
        Index("ix_submitted_document_evidence_application_id", ("application_id",)),
    ),
    "supervised_portal_runs": (
        Index("ix_supervised_portal_runs_browser_session_id", ("browser_session_id",)),
        Index("ix_supervised_portal_runs_portal", ("portal",)),
        Index("ix_supervised_portal_runs_state", ("state",)),
        Index("ix_supervised_portal_runs_workflow_id", ("workflow_id",)),
        Index("ix_supervised_portal_runs_workflow_updated", ("workflow_id", "updated_at")),
    ),
    "supervised_portal_step_evidence": (
        Index("ix_supervised_portal_step_evidence_run_id", ("run_id",)),
        Index("ix_supervised_portal_step_run_created", ("run_id", "created_at")),
    ),
    "workflow_checkpoints": (Index("ix_workflow_checkpoints_latest", ("workflow_id", "sequence")),),
    "workflow_events": (
        Index("ix_workflow_events_workflow_id", ("workflow_id",)),
        Index("ix_workflow_events_workflow_occurred", ("workflow_id", "occurred_at")),
    ),
}

# The additive application-answer migrations left these useful indexes in
# Alembic-upgraded workspaces; create-all test databases legitimately omit them.
COMPATIBLE_EXTRA_INDEXES: dict[str, tuple[Index, ...]] = {
    "application_answers": (
        Index("ix_application_answers_answer_kind", ("answer_kind",)),
        Index("ix_application_answers_status", ("status",)),
    )
}
