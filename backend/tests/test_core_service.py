from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from job_apply_pro.domain.applications import ApplicationCreate
from job_apply_pro.domain.candidate import CandidateProfileCreate, ContactDetails
from job_apply_pro.domain.checkpoints import CheckpointCreate
from job_apply_pro.domain.jobs import JobCreate
from job_apply_pro.domain.workflow import WorkflowState
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.security.keys import StaticKeyProvider
from job_apply_pro.services.core import CoreService
from job_apply_pro.storage.database import Base
from job_apply_pro.storage.models import CandidateProfileRow, WorkflowCheckpointRow
from job_apply_pro.storage.repositories import (
    ApplicationRepository,
    CandidateRepository,
    CheckpointRepository,
    JobRepository,
)


def _service(session: Session, cipher: SensitiveDataCipher) -> CoreService:
    return CoreService(
        CandidateRepository(session),
        JobRepository(session),
        ApplicationRepository(session),
        CheckpointRepository(session),
        cipher,
    )


def _memory_session() -> Session:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def test_candidate_backup_restores_without_plaintext_storage(session: Session) -> None:
    cipher = SensitiveDataCipher(StaticKeyProvider(b"c" * 32, key_id="backup-v1"))
    service = _service(session, cipher)
    profile = service.create_candidate(
        CandidateProfileCreate(
            display_name="Primary profile",
            contact=ContactDetails(
                full_name="Ada Candidate",
                email="ada@example.com",
                phone="555-0142",
            ),
        )
    )

    stored = session.scalar(select(CandidateProfileRow).where(CandidateProfileRow.id == profile.id))
    assert stored is not None
    assert "ada@example.com" not in stored.encrypted_contact

    backup = service.export_candidate(profile.id)
    restore_session = _memory_session()
    try:
        restored = _service(restore_session, cipher).restore_candidate(backup)
    finally:
        restore_session.close()

    assert restored == profile


def test_job_application_and_checkpoint_resume(session: Session) -> None:
    cipher = SensitiveDataCipher(StaticKeyProvider(b"d" * 32))
    service = _service(session, cipher)
    profile = service.create_candidate(
        CandidateProfileCreate(
            display_name="Core profile",
            contact=ContactDetails(full_name="Core User", email="core@example.com"),
        )
    )
    job = service.create_job(
        JobCreate(
            source="example-board",
            external_id="job-42",
            employer="Example Labs",
            title="Platform Engineer",
            description_hash="a" * 64,
        )
    )
    application = service.create_application(
        ApplicationCreate(workflow_id="workflow-42", profile_id=profile.id, job_id=job.id)
    )

    service.save_checkpoint(
        application.workflow_id,
        CheckpointCreate(
            state=WorkflowState.FORM_MAPPED,
            page_fingerprint="sha256:application-page",
            payload={"current_field": "work_authorization", "answer": "authorized"},
        ),
    )
    resumed = service.latest_checkpoint(application.workflow_id)
    stored = session.scalar(
        select(WorkflowCheckpointRow).where(
            WorkflowCheckpointRow.workflow_id == application.workflow_id
        )
    )

    assert resumed.sequence == 1
    assert resumed.payload["current_field"] == "work_authorization"
    assert stored is not None
    assert "authorized" not in stored.encrypted_payload
