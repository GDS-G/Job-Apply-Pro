"""Forward restore preserves recorded history; this is not a pre-call intent journal."""

import hashlib
import time
from collections.abc import Callable
from pathlib import Path

from job_apply_pro.domain.job_readiness import (
    QualificationReview,
    ReadinessSelectionReview,
    RequirementsReview,
)
from job_apply_pro.security.encryption import DecryptionError, SensitiveDataCipher
from job_apply_pro.security.keys import KeyConfigurationError
from job_apply_pro.storage.restore_gate_repository import RestoreAdmissionError, checked_path
from job_apply_pro.storage.restore_history_policy import EXACT_SETS, TABLES
from job_apply_pro.storage.restore_history_repository import (
    UNAVAILABLE,
    HistorySnapshot,
    RestoreHistoryError,
    checked_json,
    inspect_history,
    inspect_history_bytes,
    require_relational_closure,
)

__all__ = [
    "RestoreHistoryError",
    "require_preserved_history",
    "require_preserved_history_bytes",
    "require_preserved_history_snapshot",
]

# Explicit record contexts authenticate opaque snapshots without exposing them.
# Formats may change only with a reviewed policy revision, never context guessing.
ENCRYPTED = {
    "candidate_profiles": {"encrypted_contact": ("candidate:{id}:contact", True)},
    "document_versions": {"encrypted_extraction": ("document:{id}:extraction", True)},
    "answer_library": {
        "encrypted_question": ("answer:{id}:question", False),
        "encrypted_answer": ("answer:{id}:value", False),
    },
    "answer_library_revisions": {
        "encrypted_question": ("answer:{answer_id}:question", False),
        "encrypted_answer": ("answer:{answer_id}:value", False),
    },
    "application_answers": {
        "encrypted_question": ("application-answer:{id}:question", False),
        "encrypted_normalized_question": ("application-answer:{id}:normalized", False),
        "encrypted_value": ("application-answer:{id}:value", False),
        "encrypted_generated_value": ("application-answer:{id}:generated", False),
    },
    "application_field_bindings": {
        "encrypted_label": ("field-binding:{review_fingerprint}:label", False),
        "encrypted_options": ("field-binding:{review_fingerprint}:options", True),
    },
    "retrieval_chunks": {"encrypted_content": ("retrieval:{id}", False)},
    "workflow_checkpoints": {"encrypted_payload": ("checkpoint:{workflow_id}:{sequence}", True)},
    "communication_records": {"encrypted_analysis": ("communication:{id}:analysis", True)},
    "outbound_drafts": {"encrypted_payload": ("communication-draft:{id}:payload", True)},
    "calendar_mutation_plans": {"encrypted_payload": ("calendar-plan:{id}:payload", True)},
    "communication_configurations": {
        "encrypted_configuration": ("communication-configuration:{id}", True)
    },
    "provider_sync_states": {"encrypted_cursor": ("provider-sync:{provider}:cursor", True)},
    "provider_calendar_events": {
        "encrypted_event": ("calendar-event:{provider}:{event_fingerprint}:payload", True)
    },
    "oauth_credentials": {
        "encrypted_token_set": ("oauth-credential:{credential_reference}:tokens", True)
    },
    "oauth_authorization_sessions": {
        "encrypted_code_verifier": ("oauth-session:{state_hash}:verifier", False)
    },
    "ai_cache": {"encrypted_response": ("ai-cache:{key}", True)},
    "ai_media_cleanup": {
        "encrypted_resource": ("ai-media:{id}:{provider_id}:{account_fingerprint}", True)
    },
    "job_readiness_reviews": {"encrypted_payload": ("job-readiness:{application_id}:{id}", True)},
}


def _authenticate(snapshot: HistorySnapshot, cipher: SensitiveDataCipher, deadline: float) -> None:
    reviews: dict[str, RequirementsReview | QualificationReview | ReadinessSelectionReview] = {}
    for table, fields in ENCRYPTED.items():
        for row in snapshot.tables[table].values():
            if time.monotonic() > deadline:
                raise RestoreHistoryError(UNAVAILABLE)
            for field, (context, is_json) in fields.items():
                envelope = row[field]
                if envelope is None:
                    continue
                if not isinstance(envelope, str):
                    raise RestoreHistoryError(UNAVAILABLE)
                plaintext = cipher.decrypt_bytes(envelope, context=context.format_map(row)).decode(
                    "utf-8"
                )
                if is_json:
                    payload = checked_json(plaintext)
                    if table == "application_field_bindings" and field == "encrypted_options":
                        if not isinstance(payload, list):
                            raise RestoreHistoryError(UNAVAILABLE)
                    elif not isinstance(payload, dict):
                        raise RestoreHistoryError(UNAVAILABLE)
                    if table == "communication_records":
                        assert isinstance(payload, dict)
                        for key in ("source_account_key", "source_connection_fingerprint"):
                            if (payload.get(key) or "0" * 64) != row.get(key):
                                raise RestoreHistoryError(UNAVAILABLE)
                    if table == "job_readiness_reviews":
                        record: RequirementsReview | QualificationReview | ReadinessSelectionReview
                        if row["kind"] == "REQUIREMENTS":
                            record = RequirementsReview.model_validate(payload)
                        elif row["kind"] == "QUALIFICATION":
                            record = QualificationReview.model_validate(payload)
                        elif row["kind"] == "SELECTION":
                            record = ReadinessSelectionReview.model_validate(payload)
                        else:
                            raise RestoreHistoryError(UNAVAILABLE)
                        if (
                            record.id != row["id"]
                            or record.application_id != row["application_id"]
                            or record.revision != row["revision"]
                        ):
                            raise RestoreHistoryError(UNAVAILABLE)
                        reviews[record.id] = record
    _review_dependencies(snapshot, reviews, deadline)


def _review_dependencies(
    snapshot: HistorySnapshot,
    reviews: dict[str, RequirementsReview | QualificationReview | ReadinessSelectionReview],
    deadline: float,
) -> None:
    # Validate historical ownership/links, not current freshness or eligibility.
    # Stale reviews remain immutable history and are never recomputed here.
    for record in reviews.values():
        if time.monotonic() > deadline:
            raise RestoreHistoryError(UNAVAILABLE)
        app = snapshot.tables["applications"][(record.application_id,)]
        if isinstance(record, RequirementsReview):
            if (
                record.job_id != app["job_id"]
                or len({item.id for item in record.requirements}) != len(record.requirements)
                or len({item.span_id for item in record.requirements}) != len(record.requirements)
            ):
                raise RestoreHistoryError(UNAVAILABLE)
            continue
        requirements = reviews.get(record.requirements_review_id)
        if (
            not isinstance(requirements, RequirementsReview)
            or requirements.application_id != record.application_id
        ):
            raise RestoreHistoryError(UNAVAILABLE)
        if record.requirements_fingerprint != requirements.requirements_fingerprint:
            raise RestoreHistoryError(UNAVAILABLE)
        if isinstance(record, QualificationReview):
            expected = {item.id: item for item in requirements.requirements}
            if (
                len(record.findings) != len(expected)
                or {finding.requirement_id for finding in record.findings} != expected.keys()
                or record.policy_version != "reviewed-job-readiness/1"
            ):
                raise RestoreHistoryError(UNAVAILABLE)
            for finding in record.findings:
                requirement = expected.get(finding.requirement_id)
                if (
                    requirement is None
                    or requirement.text != finding.text
                    or requirement.classification != finding.classification
                    or len(set(finding.claim_ids)) != len(finding.claim_ids)
                    or (finding.status == "UNKNOWN" and bool(finding.claim_ids))
                    or (finding.status != "UNKNOWN" and not finding.claim_ids)
                ):
                    raise RestoreHistoryError(UNAVAILABLE)
                for identity in finding.claim_ids:
                    claim = snapshot.tables["candidate_claims"].get((identity,))
                    if claim is None or claim["profile_id"] != app["profile_id"]:
                        raise RestoreHistoryError(UNAVAILABLE)
            mandatory = [item for item in record.findings if item.classification == "MANDATORY"]
            preferred = [item for item in record.findings if item.classification == "PREFERRED"]
            evaluable = bool(mandatory) and not any(
                item.classification == "AMBIGUOUS" for item in record.findings
            )
            mandatory_supported = sum(item.status == "SUPPORTED" for item in mandatory)
            preferred_supported = sum(item.status == "SUPPORTED" for item in preferred)
            eligible = evaluable and mandatory_supported == len(mandatory)
            coverage = (
                (mandatory_supported + preferred_supported) / len(record.findings)
                if evaluable
                else None
            )
            if (
                record.mandatory_count != len(mandatory)
                or record.preferred_count != len(preferred)
                or record.mandatory_supported != mandatory_supported
                or record.preferred_supported != preferred_supported
                or record.evaluable != evaluable
                or record.eligible != eligible
                or record.coverage_score != coverage
                or (record.eligibility_approved and not eligible)
            ):
                raise RestoreHistoryError(UNAVAILABLE)
        else:
            qualification = reviews.get(record.qualification_review_id)
            version = snapshot.tables["document_versions"].get((record.document_version_id,))
            if (
                not isinstance(qualification, QualificationReview)
                or qualification.application_id != record.application_id
                or qualification.requirements_review_id != requirements.id
                or not qualification.eligible
                or not qualification.eligibility_approved
                or record.policy_version != "reviewed-resume-selection/1"
                or version is None
            ):
                raise RestoreHistoryError(UNAVAILABLE)
            document = snapshot.tables["documents"][(version["document_id"],)]
            if document["profile_id"] != app["profile_id"]:
                raise RestoreHistoryError(UNAVAILABLE)


def _documents(
    current: HistorySnapshot,
    candidate: HistorySnapshot,
    *,
    cipher: SensitiveDataCipher,
    documents: Path,
    staged_documents: Path | None,
) -> None:
    # The deliberately broad protected dependency domain includes every current
    # immutable version once history exists, not merely the latest selected resume.
    root = checked_path(documents)
    total_bytes = 0
    deadline = time.monotonic() + 30
    if len(candidate.tables["document_versions"]) > 1000:
        raise RestoreHistoryError(UNAVAILABLE)
    for key, version in candidate.tables["document_versions"].items():
        path_value, identity, expected = (version["storage_path"], version["id"], version["sha256"])
        if not all(isinstance(value, str) for value in (path_value, identity, expected)):
            raise RestoreHistoryError(UNAVAILABLE)
        assert (
            isinstance(path_value, str) and isinstance(identity, str) and isinstance(expected, str)
        )
        original = checked_path(Path(path_value), root=root)
        paths = [original] if key in current.tables["document_versions"] else []
        if staged_documents is not None:
            staged = checked_path(
                staged_documents / original.relative_to(root), root=staged_documents
            )
            if staged.exists():
                paths.append(staged)
        if not paths:
            paths.append(original)
        for path in paths:
            if time.monotonic() > deadline:
                raise RestoreHistoryError(UNAVAILABLE)
            if not path.is_file() or path.stat().st_nlink != 1 or path.stat().st_size > 72_000_000:
                raise RestoreHistoryError(UNAVAILABLE)
            total_bytes += path.stat().st_size
            if total_bytes > 268_435_456:
                raise RestoreHistoryError(UNAVAILABLE)
            content = cipher.decrypt_bytes(
                path.read_text(encoding="ascii"), context=f"document:{identity}:file"
            )
            if hashlib.sha256(content).hexdigest() != expected:
                raise RestoreHistoryError(
                    "Restore would change or lose protected immutable document evidence; "
                    "restore was not applied"
                )


def _require_preserved_snapshots(
    current: HistorySnapshot,
    candidate: HistorySnapshot,
    *,
    cipher: SensitiveDataCipher,
    documents: Path,
    staged_documents: Path | None,
) -> None:
    for snapshot in (current, candidate):
        if any(row["state"] != "DELETED" for row in snapshot.tables["ai_media_cleanup"].values()):
            raise RestoreHistoryError(
                "Restore is blocked by unresolved current or staged provider media cleanup"
            )
        if any(
            any(
                row[field] is not None
                for field in ("encrypted_resource", "lease_until", "next_attempt_at")
            )
            or row["reason"] not in {"DELETION_CONFIRMED", "NOT_UPLOADED", "MANUALLY_REVIEWED"}
            for row in snapshot.tables["ai_media_cleanup"].values()
        ):
            raise RestoreHistoryError(UNAVAILABLE)
    if not (current.has_history or candidate.has_history):
        return
    require_relational_closure(current)
    require_relational_closure(candidate)
    for table in TABLES:
        original, restored = current.tables[table], candidate.tables[table]
        if (table in EXACT_SETS and original != restored) or any(
            restored.get(identity) != row for identity, row in original.items()
        ):
            raise RestoreHistoryError(
                "Database restore would lose or change recorded history, its dependencies, "
                "or current authorization/session state; use a matching complete backup"
            )
    deadline = time.monotonic() + 30
    _authenticate(current, cipher, deadline)
    if candidate is not current:
        _authenticate(candidate, cipher, deadline)
    _documents(
        current,
        candidate,
        cipher=cipher,
        documents=documents,
        staged_documents=staged_documents,
    )


def _static_history_boundary(action: Callable[[], None]) -> None:
    try:
        action()
    except RestoreHistoryError:
        raise
    except (
        OSError,
        ValueError,
        TypeError,
        DecryptionError,
        KeyConfigurationError,
        RecursionError,
        RestoreAdmissionError,
        MemoryError,
    ):
        raise RestoreHistoryError(UNAVAILABLE) from None


def require_preserved_history(
    current_database: Path,
    staged_database: Path | None,
    *,
    cipher: SensitiveDataCipher,
    documents: Path,
    staged_documents: Path | None,
) -> None:
    """No data writes. Caller holds continuous exclusive restore ownership."""

    def inspect() -> None:
        current = inspect_history(current_database)
        candidate = inspect_history(staged_database) if staged_database is not None else current
        _require_preserved_snapshots(
            current,
            candidate,
            cipher=cipher,
            documents=documents,
            staged_documents=staged_documents,
        )

    _static_history_boundary(inspect)


def require_preserved_history_snapshot(
    current_database: bytes,
    staged_database: Path | None,
    *,
    cipher: SensitiveDataCipher,
    documents: Path,
    staged_documents: Path | None,
) -> None:
    """Compare a candidate with the exact current bytes retained for rollback."""

    def inspect() -> None:
        current = inspect_history_bytes(current_database)
        candidate = inspect_history(staged_database) if staged_database is not None else current
        _require_preserved_snapshots(
            current,
            candidate,
            cipher=cipher,
            documents=documents,
            staged_documents=staged_documents,
        )

    _static_history_boundary(inspect)


def require_preserved_history_bytes(
    current_database: bytes,
    candidate_database: bytes,
    *,
    cipher: SensitiveDataCipher,
    documents: Path,
    staged_documents: Path | None,
) -> None:
    """Recheck exact retained and final DB bytes without a plaintext filesystem copy."""

    def inspect() -> None:
        current = inspect_history_bytes(current_database)
        candidate = inspect_history_bytes(candidate_database)
        _require_preserved_snapshots(
            current,
            candidate,
            cipher=cipher,
            documents=documents,
            staged_documents=staged_documents,
        )

    _static_history_boundary(inspect)
