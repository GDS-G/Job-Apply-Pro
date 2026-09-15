import base64
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from job_apply_pro.api.routes.core import get_cipher
from job_apply_pro.api.routes.operations import router as operations_router
from job_apply_pro.domain.external_effects import ExternalEffectKind, ExternalEffectStatus
from job_apply_pro.domain.operations import (
    BackupCategory,
    BackupCreate,
    BackupScheduleCreate,
    LicenseEntitlement,
    LicenseStatus,
    RestoreConfirmation,
    RestoreCreate,
    RestoreStatus,
    SignedLicense,
)
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.security.keys import StaticKeyProvider
from job_apply_pro.services.backup import BackupError, BackupService
from job_apply_pro.services.external_effects import ExternalEffectService
from job_apply_pro.services.licensing import LicenseService, help_topics
from job_apply_pro.services.operations import OperationsService
from job_apply_pro.storage.communication_repository import CommunicationRepository
from job_apply_pro.storage.database import Base, get_session
from job_apply_pro.storage.external_effect_repository import ExternalEffectRepository
from job_apply_pro.storage.models import (
    ApplicationRow,
    BackupManifestRow,
    JobRow,
    ModelInvocationRow,
    WorkflowEventRow,
)
from job_apply_pro.storage.operations_repository import OperationsRepository
from restore_test_schema import stamp_current_schema


def _file_session(path: Path) -> tuple[Session, str]:
    database_url = f"sqlite:///{path.as_posix()}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    stamp_current_schema(engine)
    return Session(engine), database_url


def test_encrypted_backup_integrity_and_selective_restore(tmp_path: Path) -> None:
    session, database_url = _file_session(tmp_path / "app.db")
    documents = tmp_path / "documents"
    documents.mkdir()
    document = documents / "resume.enc"
    document.write_text("encrypted-document-envelope", encoding="utf-8")
    service = BackupService(
        OperationsRepository(session),
        SensitiveDataCipher(StaticKeyProvider(b"b" * 32)),
        database_url=database_url,
        document_dir=documents,
        backup_dir=tmp_path / "backups",
        staging_dir=tmp_path / "restore-staging",
    )
    manifest = service.create(BackupCreate(label="Before settings change"))
    archive = Path(manifest.archive_path)
    assert archive.read_text(encoding="ascii").startswith("jap:v1:test-v1:")
    assert b"encrypted-document-envelope" not in archive.read_bytes()
    verification = service.verify(manifest.id)
    assert verification.valid
    assert verification.verified_entries == 2
    schedule = service.create_schedule(
        BackupScheduleCreate(
            label="Hourly recovery point",
            categories={BackupCategory.DATABASE},
            interval_hours=1,
        )
    )
    scheduled = service.run_due_schedules(now=schedule.next_run_at)
    assert len(scheduled) == 1
    assert service.list_schedules()[0].last_run_at == schedule.next_run_at

    document.write_text("damaged-local-copy", encoding="utf-8")
    plan = service.stage_restore(manifest.id, RestoreCreate(categories={BackupCategory.DOCUMENTS}))
    applied = service.apply_offline(
        plan.id,
        RestoreConfirmation(
            fingerprint=plan.fingerprint,
            confirmation_phrase=BackupService.RESTORE_PHRASE,
        ),
    )
    assert applied.status is RestoreStatus.APPLIED
    assert document.read_text(encoding="utf-8") == "encrypted-document-envelope"
    session.close()


def test_offline_restore_rejects_changed_fingerprint_and_missing_stage(
    tmp_path: Path,
) -> None:
    session, database_url = _file_session(tmp_path / "app.db")
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "resume.enc").write_text("encrypted", encoding="utf-8")
    service = BackupService(
        OperationsRepository(session),
        SensitiveDataCipher(StaticKeyProvider(b"b" * 32)),
        database_url=database_url,
        document_dir=documents,
        backup_dir=tmp_path / "backups",
        staging_dir=tmp_path / "restore-staging",
    )
    manifest = service.create(BackupCreate(label="Failure injection"))
    plan = service.stage_restore(manifest.id, RestoreCreate(categories={BackupCategory.DOCUMENTS}))

    with pytest.raises(ValueError, match="changed after review"):
        service.apply_offline(
            plan.id,
            RestoreConfirmation(
                fingerprint="0" * 64,
                confirmation_phrase=BackupService.RESTORE_PHRASE,
            ),
        )

    staged = Path(plan.staged_path)
    (staged / "documents" / "resume.enc").unlink()
    (staged / "documents").rmdir()
    with pytest.raises(BackupError, match="missing"):
        service.apply_offline(
            plan.id,
            RestoreConfirmation(
                fingerprint=plan.fingerprint,
                confirmation_phrase=BackupService.RESTORE_PHRASE,
            ),
        )
    session.close()


def test_backup_tamper_is_detected_before_restore(tmp_path: Path) -> None:
    session, database_url = _file_session(tmp_path / "app.db")
    service = BackupService(
        OperationsRepository(session),
        SensitiveDataCipher(StaticKeyProvider(b"b" * 32)),
        database_url=database_url,
        document_dir=tmp_path / "documents",
        backup_dir=tmp_path / "backups",
        staging_dir=tmp_path / "restore-staging",
    )
    manifest = service.create(
        BackupCreate(categories={BackupCategory.DATABASE}, label="Database only")
    )
    path = Path(manifest.archive_path)
    path.write_bytes(path.read_bytes() + b"tamper")
    verification = service.verify(manifest.id)
    assert not verification.valid
    assert verification.reasons == ["ARCHIVE_HASH_MISMATCH"]
    session.close()


def test_backup_manifest_drift_is_detected(tmp_path: Path) -> None:
    session, database_url = _file_session(tmp_path / "app.db")
    service = BackupService(
        OperationsRepository(session),
        SensitiveDataCipher(StaticKeyProvider(b"b" * 32)),
        database_url=database_url,
        document_dir=tmp_path / "documents",
        backup_dir=tmp_path / "backups",
        staging_dir=tmp_path / "restore-staging",
    )
    manifest = service.create(
        BackupCreate(categories={BackupCategory.DATABASE}, label="Manifest drift")
    )
    row = session.get(BackupManifestRow, manifest.id)
    assert row is not None
    payload = dict(row.manifest_json)
    raw_entries = payload["entries"]
    assert isinstance(raw_entries, list)
    entries: list[dict[str, object]] = []
    for value in raw_entries:
        assert isinstance(value, dict)
        entries.append(dict(value))
    entries[0]["sha256"] = "0" * 64
    payload["entries"] = entries
    row.manifest_json = payload
    session.commit()

    verification = service.verify(manifest.id)

    assert not verification.valid
    assert "MANIFEST_MISMATCH" in verification.reasons
    session.close()


def _signed_license(private_key: Ed25519PrivateKey, entitlement: LicenseEntitlement) -> SecretStr:
    payload = entitlement.model_dump_json().encode()
    return SecretStr(
        SignedLicense(
            payload=base64.urlsafe_b64encode(payload).decode(),
            signature=base64.urlsafe_b64encode(private_key.sign(payload)).decode(),
        ).model_dump_json()
    )


def test_signed_license_active_grace_invalid_and_recovery_access() -> None:
    now = datetime(2026, 8, 6, tzinfo=UTC)
    private_key = Ed25519PrivateKey.generate()
    public_key = SecretStr(
        base64.urlsafe_b64encode(
            private_key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        ).decode()
    )
    entitlement = LicenseEntitlement(
        license_id="license-1",
        subject="development-user",
        device_public_key="device-key-1",
        features=["dashboard", "backup"],
        issued_at=now - timedelta(days=30),
        expires_at=now + timedelta(days=1),
        offline_grace_days=7,
    )
    active = LicenseService(public_key, _signed_license(private_key, entitlement), now=now).state()
    grace = LicenseService(
        public_key,
        _signed_license(
            private_key,
            entitlement.model_copy(update={"expires_at": now - timedelta(days=1)}),
        ),
        now=now,
    ).state()
    invalid = LicenseService(
        public_key, SecretStr('{"payload":"bad","signature":"bad"}'), now=now
    ).state()
    assert active.status is LicenseStatus.ACTIVE
    assert grace.status is LicenseStatus.GRACE_PERIOD
    assert invalid.status is LicenseStatus.INVALID
    assert active.recovery_allowed and grace.recovery_allowed and invalid.recovery_allowed


def test_empty_dashboard_reconciles_and_help_covers_recovery(session: Session) -> None:
    cipher = SensitiveDataCipher(StaticKeyProvider(b"o" * 32))
    effects = ExternalEffectService(
        ExternalEffectRepository(sessionmaker(bind=session.get_bind(), expire_on_commit=False)),
        cipher,
    )
    dashboard = OperationsService(
        OperationsRepository(session),
        CommunicationRepository(session, cipher),
        LicenseService(None, None),
        effects,
    ).dashboard()
    assert dashboard.applications.applications_total == 0
    assert dashboard.models.cost_micros == 0
    assert len(dashboard.portals) == 11
    assert all(not portal.production_enabled for portal in dashboard.portals)
    assert all(
        len(portal.replay_validated_page_types) == (7 if portal.portal == "GREENHOUSE" else 4)
        for portal in dashboard.portals
    )
    assert all(not portal.live_validated_page_types for portal in dashboard.portals)
    assert dashboard.external_effects.total == 0
    assert dashboard.unresolved_external_effects == []
    assert dashboard.license.status is LicenseStatus.DEVELOPMENT
    assert {topic.id for topic in help_topics()} >= {"backup-restore", "recovery-access"}


def test_dashboard_lists_only_bounded_privacy_safe_unresolved_effects(session: Session) -> None:
    cipher = SensitiveDataCipher(StaticKeyProvider(b"o" * 32))
    effects = ExternalEffectService(
        ExternalEffectRepository(sessionmaker(bind=session.get_bind(), expire_on_commit=False)),
        cipher,
    )
    now = datetime(2026, 9, 14, tzinfo=UTC)
    request = {"prompt": "private candidate fact must not leave the ledger boundary"}

    prepared = effects.admit(
        effect_key="operations-prepared",
        kind=ExternalEffectKind.AI_COMPLETION,
        subject_type="model_request",
        subject_id="prepared-request",
        actor="fixture",
        request=request,
        now=now,
    )
    dispatching = effects.admit(
        effect_key="operations-dispatching",
        kind=ExternalEffectKind.AI_COMPLETION,
        subject_type="model_request",
        subject_id="dispatching-request",
        actor="fixture",
        request=request,
        now=now + timedelta(seconds=1),
    )
    dispatching_attempt = effects.prepare_attempt(
        dispatching.operation.id,
        provider="fixture",
        target_code="fixture-model",
        request=request,
        now=now + timedelta(seconds=1),
    )
    effects.begin_dispatch(
        dispatching.operation.id,
        dispatching_attempt.id,
        now=now + timedelta(seconds=1),
    )
    uncertain = effects.admit(
        effect_key="operations-uncertain",
        kind=ExternalEffectKind.AI_COMPLETION,
        subject_type="model_request",
        subject_id="uncertain-request",
        actor="fixture",
        request=request,
        now=now + timedelta(seconds=2),
    )
    uncertain_attempt = effects.prepare_attempt(
        uncertain.operation.id,
        provider="fixture",
        target_code="fixture-model",
        request=request,
        now=now + timedelta(seconds=2),
    )
    effects.begin_dispatch(
        uncertain.operation.id,
        uncertain_attempt.id,
        now=now + timedelta(seconds=2),
    )
    effects.finish(
        uncertain.operation.id,
        uncertain_attempt.id,
        status=ExternalEffectStatus.UNCERTAIN,
        error_code="PROVIDER_RESPONSE_UNAVAILABLE",
        now=now + timedelta(seconds=2),
    )
    confirmed = effects.admit(
        effect_key="operations-confirmed",
        kind=ExternalEffectKind.AI_COMPLETION,
        subject_type="model_request",
        subject_id="confirmed-request",
        actor="fixture",
        request=request,
        now=now + timedelta(seconds=3),
    )
    confirmed_attempt = effects.prepare_attempt(
        confirmed.operation.id,
        provider="fixture",
        target_code="fixture-model",
        request=request,
        now=now + timedelta(seconds=3),
    )
    effects.begin_dispatch(
        confirmed.operation.id,
        confirmed_attempt.id,
        now=now + timedelta(seconds=3),
    )
    effects.finish(
        confirmed.operation.id,
        confirmed_attempt.id,
        status=ExternalEffectStatus.CONFIRMED,
        result_reference="invocation-fixture",
        result={"accepted": True},
        now=now + timedelta(seconds=3),
    )
    for index in range(21):
        effects.admit(
            effect_key=f"operations-older-prepared-{index}",
            kind=ExternalEffectKind.AI_EMBEDDING,
            subject_type="model_request",
            subject_id=f"older-prepared-{index}",
            actor="fixture",
            request=request,
            now=now - timedelta(seconds=index + 1),
        )

    dashboard = OperationsService(
        OperationsRepository(session),
        CommunicationRepository(session, cipher),
        LicenseService(None, None),
        effects,
    ).dashboard()

    assert prepared.created and dashboard.external_effects.total == 25
    assert dashboard.external_effects.unresolved == 24
    assert len(dashboard.unresolved_external_effects) == OperationsService.ATTENTION_LIMIT
    assert [item.status for item in dashboard.unresolved_external_effects[:3]] == [
        ExternalEffectStatus.UNCERTAIN,
        ExternalEffectStatus.DISPATCHING,
        ExternalEffectStatus.PREPARED,
    ]
    assert all(
        item.subject_id != "confirmed-request" for item in dashboard.unresolved_external_effects
    )
    assert "private candidate fact" not in dashboard.model_dump_json()


def test_dashboard_api_wires_privacy_safe_effect_visibility(session: Session) -> None:
    cipher = SensitiveDataCipher(StaticKeyProvider(b"o" * 32))
    effects = ExternalEffectService(
        ExternalEffectRepository(sessionmaker(bind=session.get_bind(), expire_on_commit=False)),
        cipher,
    )
    effects.admit(
        effect_key="operations-api-prepared",
        kind=ExternalEffectKind.AI_EMBEDDING,
        subject_type="model_request",
        subject_id="safe-request-reference",
        actor="fixture-actor-must-not-be-public",
        request={"input": "private embedding input"},
    )
    application = FastAPI()
    application.include_router(operations_router, prefix="/api/v1")
    application.dependency_overrides[get_session] = lambda: session
    application.dependency_overrides[get_cipher] = lambda: cipher

    with TestClient(application) as client:
        response = client.get("/api/v1/operations/dashboard")

    assert response.status_code == 200
    payload = response.json()
    assert payload["external_effects"]["unresolved"] == 1
    assert payload["unresolved_external_effects"] == [
        {
            "id": payload["unresolved_external_effects"][0]["id"],
            "kind": "AI_EMBEDDING",
            "subject_type": "model_request",
            "subject_id": "safe-request-reference",
            "status": "PREPARED",
            "result_reference": None,
            "error_code": None,
            "attempt_count": 0,
            "created_at": payload["unresolved_external_effects"][0]["created_at"],
            "updated_at": payload["unresolved_external_effects"][0]["updated_at"],
            "completed_at": None,
            "reconciliation_available": False,
            "reconciliation_kind": None,
            "reconciled_at": None,
        }
    ]
    assert "private embedding input" not in response.text
    assert "fixture-actor-must-not-be-public" not in response.text


def test_metrics_reconcile_attempts_confirmations_and_model_cost(session: Session) -> None:
    now = datetime(2026, 8, 5, tzinfo=UTC)
    session.add_all(
        [
            JobRow(
                id="job-1",
                source="fixture",
                external_id="external-1",
                employer="Example Co",
                title="Platform Engineer",
                location="Remote",
                source_url="https://example.invalid/job-1",
                description_hash="a" * 64,
                discovered_at=now,
            ),
            ApplicationRow(
                id="application-1",
                workflow_id="workflow-1",
                profile_id="profile-1",
                job_id="job-1",
                state="SUBMISSION_CONFIRMED",
                selected_document_version_id=None,
                created_at=now,
                updated_at=now,
            ),
            WorkflowEventRow(
                id="event-1",
                workflow_id="workflow-1",
                sequence=1,
                prior_state="READY_TO_SUBMIT",
                next_state="SUBMISSION_ATTEMPTED",
                actor="fixture",
                cause="verified submit",
                verification="VERIFIED",
                retry_count=0,
                occurred_at=now,
            ),
            WorkflowEventRow(
                id="event-2",
                workflow_id="workflow-1",
                sequence=2,
                prior_state="SUBMISSION_ATTEMPTED",
                next_state="SUBMISSION_CONFIRMED",
                actor="fixture",
                cause="confirmation evidence",
                verification="VERIFIED",
                retry_count=0,
                occurred_at=now,
            ),
            ModelInvocationRow(
                id="invocation-1",
                profile_id=None,
                task_type="qualification",
                provider="local-fixture",
                model="fixture-v1",
                prompt_version="1",
                schema_version="1",
                input_hash="b" * 64,
                cache_key="c" * 64,
                classification="ROUTINE",
                status="COMPLETED",
                input_tokens=120,
                output_tokens=30,
                cost_micros=750,
                attempts=1,
                route_json=["local-fixture"],
                latency_ms=40,
                error_code=None,
                created_at=now,
                completed_at=now,
            ),
        ]
    )
    session.commit()

    repository = OperationsRepository(session)

    assert repository.application_metrics().model_dump() == {
        "jobs_discovered": 1,
        "applications_total": 1,
        "submission_attempted": 1,
        "submission_confirmed": 1,
        "tracking_active": 0,
        "failed": 0,
        "duplicated": 0,
        "interviews_received": 0,
        "offers_received": 0,
        "recruiter_messages": 0,
    }
    model_metrics = repository.model_metrics()
    assert (model_metrics.input_tokens, model_metrics.output_tokens) == (120, 30)
    assert model_metrics.cost_micros == 750
    report = repository.application_report()
    assert report[0].submission_attempted and report[0].submission_confirmed
