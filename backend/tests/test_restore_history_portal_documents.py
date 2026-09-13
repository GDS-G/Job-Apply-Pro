"""Synthetic recorded portal effects and immutable files survive forward restore admission."""

import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import select

from job_apply_pro.domain.browser import BrowserAction, BrowserActionKind
from job_apply_pro.domain.challenges import ChallengeDetection, ChallengeSessionSnapshot
from job_apply_pro.domain.operations import BackupCategory, BackupCreate
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.security.keys import StaticKeyProvider
from job_apply_pro.services.restore_history import RestoreHistoryError, require_preserved_history
from job_apply_pro.storage.models import (
    ApplicationAnswerRow,
    ApplicationFieldBindingRow,
    ApplicationFieldExecutionRow,
    ApplicationRow,
    BrowserActionRow,
    BrowserSessionRow,
    CandidateClaimRow,
    ChallengeEventRow,
    ChallengeSessionRow,
    CommunicationRecordRow,
    DocumentRow,
    DocumentVersionRow,
    JobReadinessReviewRow,
    OutboundDraftRow,
    SubmittedDocumentEvidenceRow,
    SupervisedPortalRunRow,
    SupervisedPortalStepEvidenceRow,
    WorkflowEventRow,
)
from test_forward_restore_history import _NOW, _HistoryRestore
from test_forward_restore_history import history as history
from test_greenhouse_discovery_import import profile
from test_job_readiness import Fixture
from test_mail_attachment_boundary import _command, _confirmation, _service
from test_supervised_portal_execution import _observation


@pytest.fixture
def graph(history: _HistoryRestore) -> _HistoryRestore:
    history = replace(history, cipher=SensitiveDataCipher(StaticKeyProvider(b"g" * 32)))
    observation = _observation(
        page_type="APPLICATION", fingerprint="synthetic-page", visible_text="Synthetic"
    )
    with history.session() as session:
        fixture = Fixture(session, history.root)
        fixture.ready_to_select()
        fixture.service.approve_resume(fixture.selection())
        app = session.get(ApplicationRow, fixture.application_id)
        assert app is not None
        session.add(
            BrowserSessionRow(
                id="browser-1",
                workflow_id=app.workflow_id,
                engine="chromium",
                profile_name="synthetic",
                user_data_dir=str(history.root / "browser"),
                artifact_dir=str(history.root / "browser-artifacts"),
                headless=True,
                state="USER_TAKEOVER",
                current_url=observation.url,
                allowed_origins_json=["https://www.linkedin.com"],
                last_observation_json=observation.model_dump(mode="json"),
                trace_path=None,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        session.add(
            SupervisedPortalRunRow(
                id="run-1",
                portal="LINKEDIN",
                workflow_id=app.workflow_id,
                browser_session_id="browser-1",
                state="READY_TO_SUBMIT",
                current_url=observation.url,
                allowed_origins_json=["https://www.linkedin.com"],
                page_fingerprint="synthetic-page",
                current_match_json=None,
                disposition="USER_ACTION_REQUIRED",
                intervention_reasons_json=[],
                trace_path=None,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        session.add(
            ApplicationAnswerRow(
                id="answer-1",
                application_id=app.id,
                profile_id=app.profile_id,
                job_id=app.job_id,
                canonical_field="email",
                revision=1,
                answer_kind="SHORT_TEXT",
                validation_rules_json={},
                encrypted_value=history.cipher.encrypt_bytes(
                    b"candidate@example.test", context="application-answer:answer-1:value"
                ),
                provenance="Synthetic operator",
                status="REVIEWED",
                source_type="USER_REVIEWED",
                confidence=1,
                approved=True,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        session.add(
            ApplicationFieldBindingRow(
                id="binding-1",
                application_id=app.id,
                application_answer_id="answer-1",
                answer_revision=1,
                portal="LINKEDIN",
                page_fingerprint="synthetic-page",
                control_key="email",
                control_kind="EMAIL",
                required=False,
                canonical_field="email",
                confidence=1,
                binding_source="USER_CONFIRMED",
                answer_source="USER_REVIEWED",
                answer_kind="SHORT_TEXT",
                validation_rules_json={},
                automation_permission="AUTOFILL_ALLOWED",
                review_fingerprint="b" * 64,
                encrypted_label=history.cipher.encrypt_bytes(
                    b"Email", context=f"field-binding:{'b' * 64}:label"
                ),
                encrypted_options=history.cipher.encrypt_bytes(
                    b"[]", context=f"field-binding:{'b' * 64}:options"
                ),
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        challenge = ChallengeSessionSnapshot.model_validate(
            {
                "id": "challenge-1",
                "workflow_id": app.workflow_id,
                "browser_session_id": "browser-1",
                "resume_state": "DOCUMENTS_SELECTED",
                "detection": ChallengeDetection.model_validate(
                    {
                        "kind": "QUESTIONNAIRE",
                        "page_type": "QUESTIONNAIRE",
                        "page_fingerprint": "synthetic-page",
                        "detected_at": _NOW,
                    }
                ),
                "status": "IN_PROGRESS",
                "instructions": "Synthetic local evidence only",
                "questions": [],
                "answers": [],
                "current_position": 0,
                "flagged_question_ids": [],
                "time_limit_seconds": None,
                "elapsed_seconds": 0,
                "remaining_seconds": None,
                "created_at": _NOW,
                "updated_at": _NOW,
            }
        )
        session.add(
            ChallengeSessionRow(
                id=challenge.id,
                workflow_id=app.workflow_id,
                browser_session_id="browser-1",
                kind=challenge.detection.kind.value,
                status=challenge.status.value,
                snapshot_json=challenge.model_dump(mode="json"),
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        session.commit()
    return history


def _admit(graph: _HistoryRestore) -> None:
    require_preserved_history(
        graph.database,
        None,
        cipher=graph.cipher,
        documents=graph.documents,
        staged_documents=None,
    )


def _version(graph: _HistoryRestore) -> tuple[str, Path]:
    with graph.session() as session:
        version = session.scalar(select(DocumentVersionRow))
        assert version is not None
        return version.id, Path(version.storage_path)


def test_same_history_with_reviewed_readiness_portal_graph_and_field_options_restores(
    graph: _HistoryRestore,
) -> None:
    _admit(graph)
    graph.assert_applied(graph.backup())


@pytest.mark.parametrize(
    "event",
    [
        "browser_verified",
        "browser_uncertain",
        "submission_uncertain",
        "submission_confirmed",
        "field_verified",
        "field_uncertain",
        "submitted_document",
        "portal_step",
        "challenge_completed",
        "challenge_event",
        "workflow_event",
    ],
)
def test_encrypted_backup_before_recorded_portal_effect_is_refused(
    graph: _HistoryRestore,
    event: str,
) -> None:
    backup = graph.backup()
    with graph.session() as session:
        app = session.scalar(select(ApplicationRow))
        assert app is not None
        if event.startswith("browser_"):
            action = BrowserAction(kind=BrowserActionKind.CLICK, intended_result="Synthetic click")
            session.add(
                BrowserActionRow(
                    id="action-1",
                    session_id="browser-1",
                    sequence=1,
                    action_json=action.model_dump(mode="json"),
                    verified=event == "browser_verified",
                    attempts=1,
                    observation_json=_observation(
                        page_type="APPLICATION",
                        fingerprint="synthetic-page",
                        visible_text="Synthetic",
                    ).model_dump(mode="json"),
                    error=None,
                    created_at=_NOW,
                )
            )
        elif event.startswith("submission_"):
            run = session.get(SupervisedPortalRunRow, "run-1")
            assert run is not None
            run.state = (
                "SUBMISSION_CONFIRMED" if event.endswith("confirmed") else "SUBMISSION_UNCERTAIN"
            )
        elif event.startswith("field_"):
            session.add(
                ApplicationFieldExecutionRow(
                    id="execution-1",
                    binding_id="binding-1",
                    application_id=app.id,
                    application_answer_id="answer-1",
                    answer_revision=1,
                    supervised_run_id="run-1",
                    browser_session_id="browser-1",
                    portal="LINKEDIN",
                    page_fingerprint_before="synthetic-page",
                    page_fingerprint_after="synthetic-page",
                    control_key="email",
                    action_kind="FILL",
                    verified=event == "field_verified",
                    action_fingerprint="c" * 64,
                    error=None,
                    created_at=_NOW,
                )
            )
        elif event == "submitted_document":
            version = session.scalar(select(DocumentVersionRow))
            assert version is not None
            session.add(
                SubmittedDocumentEvidenceRow(
                    id="upload-1",
                    application_id=app.id,
                    document_version_id=version.id,
                    role="RESUME",
                    file_name=version.file_name,
                    sha256=version.sha256,
                    upload_fingerprint="synthetic-upload",
                    captured_at=_NOW,
                )
            )
        elif event == "portal_step":
            session.add(
                SupervisedPortalStepEvidenceRow(
                    id="step-1",
                    run_id="run-1",
                    sequence=1,
                    disposition="CONFIRMATION_UNCERTAIN",
                    capability=None,
                    page_type="APPLICATION",
                    before_fingerprint="synthetic-page",
                    after_fingerprint="synthetic-page",
                    action_kind="CLICK",
                    action_fingerprint="d" * 64,
                    verified=False,
                    intervention_reasons_json=[],
                    created_at=_NOW,
                )
            )
        elif event == "challenge_completed":
            challenge = session.get(ChallengeSessionRow, "challenge-1")
            assert challenge is not None
            challenge.status = "COMPLETED"
            challenge.snapshot_json = {**challenge.snapshot_json, "status": "COMPLETED"}
        elif event == "challenge_event":
            session.add(
                ChallengeEventRow(
                    id="event-1",
                    session_id="challenge-1",
                    sequence=1,
                    event_type="USER_COMPLETION_RECORDED",
                    details_json={},
                    occurred_at=_NOW,
                )
            )
        else:
            session.add(
                WorkflowEventRow(
                    id="event-1",
                    workflow_id=app.workflow_id,
                    sequence=100,
                    prior_state="DOCUMENTS_SELECTED",
                    next_state="USER_TAKEOVER",
                    actor="synthetic",
                    cause="User review required",
                    verification="NOT_REQUIRED",
                    retry_count=0,
                    occurred_at=_NOW,
                )
            )
        session.commit()
    graph.assert_refused(backup)


@pytest.mark.parametrize(
    "damage", ["missing", "non_ascii", "invalid_envelope", "wrong_content", "outside_root"]
)
def test_existing_protected_document_damage_is_refused_before_writes(
    graph: _HistoryRestore,
    damage: str,
) -> None:
    identity, path = _version(graph)
    if damage == "missing":
        path.unlink()
    elif damage == "non_ascii":
        path.write_bytes(b"\xff")
    elif damage == "invalid_envelope":
        path.write_text("invalid", encoding="ascii")
    elif damage == "wrong_content":
        path.write_text(
            graph.cipher.encrypt_bytes(b"changed", context=f"document:{identity}:file"),
            encoding="ascii",
        )
    else:
        outside = graph.root / "outside.enc"
        outside.write_bytes(path.read_bytes())
        with closing(sqlite3.connect(graph.database)) as connection:
            connection.execute("UPDATE document_versions SET storage_path=?", (str(outside),))
            connection.commit()
    before = graph.database.read_bytes()
    with pytest.raises(RestoreHistoryError):
        _admit(graph)
    assert graph.database.read_bytes() == before


@pytest.mark.parametrize("changed", [True, False])
def test_documents_only_archive_rechecks_prospective_protected_plaintext(
    graph: _HistoryRestore,
    changed: bool,
) -> None:
    identity, path = _version(graph)
    original = path.read_bytes()
    plaintext = graph.cipher.decrypt_bytes(
        original.decode("ascii"), context=f"document:{identity}:file"
    )
    path.write_text(
        graph.cipher.encrypt_bytes(
            b"Different bytes cannot replace submitted evidence" if changed else plaintext,
            context=f"document:{identity}:file",
        ),
        encoding="ascii",
    )
    with graph.session() as session:
        backup = graph.backup_service(session).create(
            BackupCreate(categories={BackupCategory.DOCUMENTS})
        )
    path.write_bytes(original)
    if changed:
        graph.assert_refused(backup, message="protected immutable document evidence")
    else:
        graph.assert_applied(backup)
        assert path.read_bytes() != original
        assert (
            graph.cipher.decrypt_bytes(path.read_text("ascii"), context=f"document:{identity}:file")
            == plaintext
        )


@pytest.mark.parametrize(
    "table,column,value",
    [
        ("application_answers", "source_answer_id", "missing-answer"),
        (
            "application_answers",
            "retrieval_results_json",
            json.dumps([{"source_type": "ANSWER", "source_id": "missing-answer"}]),
        ),
        ("candidate_claims", "superseded_by_id", "missing-claim"),
        ("retrieval_chunks", "source_id", "missing-source"),
        ("application_field_bindings", "application_answer_id", "missing-answer"),
        ("application_field_bindings", "answer_revision", 100),
        ("document_selection_audits", "document_id", "missing-document"),
    ],
)
def test_missing_or_inconsistent_dependency_refuses_even_identical_snapshot(
    graph: _HistoryRestore,
    table: str,
    column: str,
    value: str | int,
) -> None:
    with closing(sqlite3.connect(graph.database)) as connection:
        connection.execute(
            f'UPDATE "{table}" SET "{column}"=? WHERE rowid=(SELECT rowid FROM "{table}" LIMIT 1)',
            (value,),
        )
        connection.commit()
    before = graph.database.read_bytes()
    with pytest.raises(RestoreHistoryError, match="cannot be verified"):
        _admit(graph)
    assert graph.database.read_bytes() == before


@pytest.mark.parametrize("field,value", [("sha256", "f" * 64), ("file_name", "other-resume.txt")])
def test_submitted_document_metadata_must_match_its_protected_version(
    graph: _HistoryRestore,
    field: str,
    value: str,
) -> None:
    with graph.session() as session:
        app = session.scalar(select(ApplicationRow))
        version = session.scalar(select(DocumentVersionRow))
        assert app is not None and version is not None
        evidence = SubmittedDocumentEvidenceRow(
            id="upload-1",
            application_id=app.id,
            document_version_id=version.id,
            role="RESUME",
            file_name=version.file_name,
            sha256=version.sha256,
            upload_fingerprint="synthetic-upload",
            captured_at=_NOW,
        )
        setattr(evidence, field, value)
        session.add(evidence)
        session.commit()
    with pytest.raises(RestoreHistoryError, match="cannot be verified"):
        _admit(graph)


@pytest.mark.parametrize("workflow", ["foreign", "missing"])
def test_workflow_bound_draft_cannot_reference_another_profiles_document(
    graph: _HistoryRestore,
    workflow: str,
) -> None:
    with graph.session() as session:
        app = session.scalar(select(ApplicationRow))
        version = session.scalar(select(DocumentVersionRow))
        assert app is not None and version is not None
        other_profile = profile(session, "Other synthetic profile")
        session.add(
            ApplicationRow(
                id="other-app",
                workflow_id="other-workflow",
                profile_id=other_profile,
                job_id=app.job_id,
                state="DISCOVERED",
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        session.add(
            CommunicationRecordRow(
                id="record-1",
                provider="GMAIL",
                provider_message_id="message-1",
                provider_thread_id="thread-1",
                source_account_key="0" * 64,
                source_connection_fingerprint="0" * 64,
                category="OTHER",
                workflow_id=None,
                requires_review=True,
                encrypted_analysis=graph.cipher.encrypt_json(
                    {}, context="communication:record-1:analysis"
                ),
                received_at=_NOW,
                created_at=_NOW,
            )
        )
        session.add(
            OutboundDraftRow(
                id="draft-1",
                analysis_id="record-1",
                workflow_id="other-workflow" if workflow == "foreign" else None,
                provider="GMAIL",
                provider_thread_id="thread-1",
                category="OTHER",
                policy="MANUAL_ONLY",
                document_version_ids_json=[version.id],
                fingerprint="f" * 64,
                encrypted_payload=graph.cipher.encrypt_json(
                    {}, context="communication-draft:draft-1:payload"
                ),
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        session.commit()
    with pytest.raises(RestoreHistoryError, match="cannot be verified"):
        _admit(graph)


@pytest.mark.parametrize(
    "kind,change",
    [
        ("REQUIREMENTS", "missing_fields"),
        ("REQUIREMENTS", "identity"),
        ("QUALIFICATION", "requirements_id"),
        ("QUALIFICATION", "claim_id"),
        ("QUALIFICATION", "requirements_fingerprint"),
        ("SELECTION", "qualification_id"),
        ("SELECTION", "version_id"),
    ],
)
def test_authenticated_readiness_payload_requires_historical_dependency_closure(
    graph: _HistoryRestore,
    kind: str,
    change: str,
) -> None:
    with graph.session() as session:
        row = session.scalar(
            select(JobReadinessReviewRow).where(JobReadinessReviewRow.kind == kind)
        )
        assert row is not None
        context = f"job-readiness:{row.application_id}:{row.id}"
        payload = graph.cipher.decrypt_json(row.encrypted_payload, context=context)
        if change == "missing_fields":
            payload = {}
        elif change == "identity":
            payload["id"] = "missing-review"
        elif change == "claim_id":
            findings = payload["findings"]
            assert isinstance(findings, list) and isinstance(findings[0], dict)
            findings[0]["claim_ids"] = ["missing-claim"]
        else:
            field = {
                "requirements_id": "requirements_review_id",
                "requirements_fingerprint": "requirements_fingerprint",
                "qualification_id": "qualification_review_id",
                "version_id": "document_version_id",
            }[change]
            payload[field] = "e" * 64
        row.encrypted_payload = graph.cipher.encrypt_json(payload, context=context)
        session.commit()
    with pytest.raises(RestoreHistoryError, match="cannot be verified"):
        _admit(graph)


def test_historical_readiness_can_be_stale_without_rewriting_or_advancing_it(
    graph: _HistoryRestore,
) -> None:
    with graph.session() as session:
        claim = session.scalar(select(CandidateClaimRow))
        document = session.scalar(select(DocumentRow))
        assert claim is not None and document is not None
        claim.locked = False
        document.archived = True
        session.commit()
    before = graph.database.read_bytes()
    _admit(graph)
    assert graph.database.read_bytes() == before


def test_identical_real_recorded_mail_attempt_restores_without_replaying_provider(
    history: _HistoryRestore,
) -> None:
    from job_apply_pro.domain.communications import IntegrationProvider, MutationStatus

    history = replace(history, cipher=SensitiveDataCipher(StaticKeyProvider(b"a" * 32)))
    with history.session() as session:
        mail, _, adapter, analysis_id = _service(session, IntegrationProvider.GMAIL)
        draft = mail.create_draft(
            _command(IntegrationProvider.GMAIL, analysis_id=analysis_id, attachments=False)
        )
        audit = mail.send_draft(draft.id, _confirmation(draft))
        assert audit.status is MutationStatus.ACCEPTED
    assert len(adapter.sent) == 1
    history.assert_applied(history.backup())
    assert len(adapter.sent) == 1


@pytest.mark.parametrize(
    "table,column,value",
    [
        ("browser_sessions", "state", "UNKNOWN_FUTURE_STATE"),
        ("browser_sessions", "engine", "unknown-engine"),
        ("browser_sessions", "last_observation_json", "{}"),
        ("supervised_portal_runs", "portal", "UNKNOWN_FUTURE_PORTAL"),
        ("supervised_portal_runs", "state", "UNKNOWN_FUTURE_STATE"),
        ("supervised_portal_runs", "disposition", "UNKNOWN_FUTURE_DISPOSITION"),
        ("challenge_sessions", "kind", "UNKNOWN_FUTURE_CHALLENGE"),
        ("challenge_sessions", "status", "UNKNOWN_FUTURE_STATUS"),
        ("challenge_sessions", "snapshot_json", "{}"),
        ("challenge_sessions", "status", "COMPLETED"),
        ("applications", "state", "UNKNOWN_FUTURE_STATE"),
    ],
)
def test_recorded_state_and_browser_challenge_shapes_must_be_supported(
    graph: _HistoryRestore,
    table: str,
    column: str,
    value: str,
) -> None:
    with closing(sqlite3.connect(graph.database)) as connection:
        connection.execute(f'UPDATE "{table}" SET "{column}"=?', (value,))
        connection.commit()
    with pytest.raises(RestoreHistoryError, match="cannot be verified"):
        _admit(graph)


def test_unrecognized_table_under_known_revision_is_not_silently_ignored(
    graph: _HistoryRestore,
) -> None:
    with closing(sqlite3.connect(graph.database)) as connection:
        connection.execute("CREATE TABLE unreviewed_future_effects (id TEXT PRIMARY KEY)")
        connection.commit()
    with pytest.raises(RestoreHistoryError, match="cannot be verified"):
        _admit(graph)
