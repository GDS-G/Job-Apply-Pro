import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from job_apply_pro.domain.candidate import CandidateProfileCreate, ContactDetails
from job_apply_pro.domain.job_discovery import GreenhouseImportRequest
from job_apply_pro.domain.workbench import WorkflowControlAction, WorkflowControlCommand
from job_apply_pro.domain.workflow import WorkflowState
from job_apply_pro.portals.greenhouse import GreenhousePublicBoardClient
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.security.keys import StaticKeyProvider
from job_apply_pro.services.core import CoreService
from job_apply_pro.services.job_discovery import GreenhouseDiscoveryService
from job_apply_pro.services.workbench import WorkbenchService, WorkbenchStateError
from job_apply_pro.storage.database import Base
from job_apply_pro.storage.job_discovery_repository import (
    GreenhouseDiscoveryRepository,
    GreenhouseImportConflictError,
)
from job_apply_pro.storage.models import (
    ApplicationRow,
    BrowserSessionRow,
    FitScoreRow,
    JobDiscoverySnapshotRow,
    JobRequirementRow,
    JobRow,
    WorkflowEventRow,
)
from job_apply_pro.storage.repositories import (
    ApplicationRepository,
    CandidateRepository,
    CheckpointRepository,
    JobRepository,
    WorkbenchRepository,
)
from test_greenhouse_public_client import BOARD, POSTING_ID, client_for, posting, review


def profile(session: Session, name: str = "Synthetic Profile") -> str:
    core = CoreService(
        CandidateRepository(session),
        JobRepository(session),
        ApplicationRepository(session),
        CheckpointRepository(session),
        SensitiveDataCipher(StaticKeyProvider(b"g" * 32)),
    )
    return core.create_candidate(
        CandidateProfileCreate(
            display_name=name,
            contact=ContactDetails(full_name=name, email="private-profile@example.invalid"),
        )
    ).id


def command(profile_id: str) -> GreenhouseImportRequest:
    return GreenhouseImportRequest(
        board_token=BOARD,
        posting_id=POSTING_ID,
        profile_id=profile_id,
        review_fingerprint=review(client_for(posting())).review_fingerprint,
    )


def service(
    session: Session, client: GreenhousePublicBoardClient | None = None
) -> GreenhouseDiscoveryService:
    return GreenhouseDiscoveryService(
        GreenhouseDiscoveryRepository(session), client or client_for(posting())
    )


def test_import_is_local_exact_immutable_and_idempotent_across_profiles(session: Session) -> None:
    first_profile = profile(session)
    second_profile = profile(session, "Other profile")
    requests: list[httpx.Request] = []
    importer = service(session, client_for(posting(), requests))
    first = importer.import_job(command(first_profile))
    assert first.outcome == "IMPORTED" and first.job and first.workflow
    assert first.job.external_id == f"{BOARD}:{POSTING_ID}"
    assert (
        first.job.description_hash
        == hashlib.sha256(review(client_for(posting())).description.encode()).hexdigest()
    )
    assert first.workflow.state is WorkflowState.DEDUPLICATED
    assert first.workflow.allowed_controls == []
    assert [item.next_state for item in first.workflow.events] == [WorkflowState.DEDUPLICATED]
    snapshot = session.get(JobDiscoverySnapshotRow, first.job.id)
    assert snapshot is not None
    saved_json = dict(snapshot.review_json)
    duplicate = importer.import_job(command(first_profile))
    other_profile = importer.import_job(command(second_profile))
    assert duplicate.outcome == "EXISTING" and duplicate.workflow
    assert duplicate.workflow.workflow_id == first.workflow.workflow_id
    assert other_profile.outcome == "IMPORTED" and other_profile.job and other_profile.workflow
    assert other_profile.job.id == first.job.id
    assert other_profile.workflow.workflow_id != first.workflow.workflow_id
    assert snapshot.review_json == saved_json
    assert session.scalar(select(func.count(JobRow.id))) == 1
    assert session.scalar(select(func.count(ApplicationRow.id))) == 2
    assert session.scalar(select(func.count(JobDiscoverySnapshotRow.job_id))) == 1
    for model in (FitScoreRow, JobRequirementRow, BrowserSessionRow):
        assert session.scalar(select(func.count()).select_from(model)) == 0
    for request in requests:
        assert request.method == "GET" and not request.content
        assert first_profile not in str(request.url) and second_profile not in str(request.url)
        assert "private-profile" not in str(request.headers)


def test_stale_review_and_source_changed_are_distinct_and_preserve_old_record(
    session: Session,
) -> None:
    profile_id = profile(session)
    original = service(session).import_job(command(profile_id))
    assert original.job
    snapshot = session.get(JobDiscoverySnapshotRow, original.job.id)
    assert snapshot
    before = dict(snapshot.review_json)
    changed_client = client_for({**posting(), "content": "New responsibilities"})
    importer = service(session, changed_client)
    stale = importer.import_job(command(profile_id))
    assert stale.outcome == "STALE_REVIEW" and stale.workflow is None
    changed_command = command(profile_id).model_copy(
        update={
            "review_fingerprint": review(changed_client).review_fingerprint,
        }
    )
    for _ in range(2):
        changed = importer.import_job(changed_command)
        assert changed.outcome == "SOURCE_CHANGED" and changed.workflow is None
        assert "not supported" in changed.notice
    assert snapshot.review_json == before
    assert session.scalar(select(func.count(ApplicationRow.id))) == 1
    assert JobRepository(session).get(original.job.id) == original.job


@pytest.mark.parametrize("status", [404, 410])
def test_gone_posting_does_not_create_records(session: Session, status: int) -> None:
    profile_id = profile(session)
    client = GreenhousePublicBoardClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(status))
    )
    result = service(session, client).import_job(command(profile_id))
    assert result.outcome == "SOURCE_UNAVAILABLE"
    assert session.scalar(select(func.count(JobRow.id))) == 0


def test_missing_profile_refuses_before_network(session: Session) -> None:
    def no_network(_request: httpx.Request) -> httpx.Response:
        pytest.fail("A missing local profile must not contact the board")

    importer = service(
        session, GreenhousePublicBoardClient(transport=httpx.MockTransport(no_network))
    )
    with pytest.raises(GreenhouseImportConflictError):
        importer.import_job(command("missing-profile"))


def test_commit_failure_rolls_back_job_snapshot_application_and_event(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile_id = profile(session)

    def fail_commit() -> None:
        session.flush()
        raise RuntimeError("synthetic interrupted local import")

    monkeypatch.setattr(session, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="synthetic"):
        service(session).import_job(command(profile_id))
    for model in (JobRow, JobDiscoverySnapshotRow, ApplicationRow, WorkflowEventRow):
        assert session.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.parametrize("action", list(WorkflowControlAction))
def test_imported_workflows_cannot_use_synthetic_workbench_controls(
    session: Session, action: WorkflowControlAction
) -> None:
    result = service(session).import_job(command(profile(session)))
    assert result.workflow
    workbench = WorkbenchService(
        CandidateRepository(session),
        JobRepository(session),
        ApplicationRepository(session),
        WorkbenchRepository(session),
    )
    with pytest.raises(WorkbenchStateError, match="mock workbench"):
        workbench.control_workflow(
            result.workflow.workflow_id, WorkflowControlCommand(action=action)
        )
    assert workbench.get_workflow(result.workflow.workflow_id) == result.workflow


@pytest.mark.parametrize("cross_profile", [False, True])
def test_concurrent_imports_converge_without_partial_rows(
    tmp_path: Path, cross_profile: bool
) -> None:
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'synthetic.db').as_posix()}", connect_args={"timeout": 15}
    )
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            profile_id = profile(session)
            second_profile_id = profile(session, "Other profile") if cross_profile else profile_id
        barrier = Barrier(2)

        def submit(target_profile: str) -> str:
            with Session(engine) as session:
                barrier.wait(timeout=10)
                result = service(session).import_job(command(target_profile))
                assert result.workflow
                return result.workflow.workflow_id

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(submit, [profile_id, second_profile_id]))
        assert (results[0] != results[1]) is cross_profile
        with Session(engine) as session:
            for model in (JobRow, JobDiscoverySnapshotRow):
                assert session.scalar(select(func.count()).select_from(model)) == 1
            for application_model in (ApplicationRow, WorkflowEventRow):
                assert session.scalar(select(func.count()).select_from(application_model)) == (
                    2 if cross_profile else 1
                )
    finally:
        engine.dispose()


def test_identity_collision_without_discovery_snapshot_is_not_adopted(session: Session) -> None:
    profile_id = profile(session)
    original = service(session).import_job(command(profile_id))
    assert original.job
    snapshot = session.get(JobDiscoverySnapshotRow, original.job.id)
    assert snapshot
    session.delete(snapshot)
    session.commit()
    result = service(session).import_job(command(profile_id))
    assert result.outcome == "SOURCE_CHANGED"


def test_application_identity_collision_does_not_rebind_profile_or_job(session: Session) -> None:
    first_profile = profile(session)
    original = service(session).import_job(command(first_profile))
    assert original.job and original.workflow
    application = session.scalar(select(ApplicationRow))
    assert application
    other = profile(session, "Other profile")
    application.profile_id = other
    session.commit()
    with pytest.raises(GreenhouseImportConflictError):
        service(session).import_job(command(first_profile))
    saved_application = ApplicationRepository(session).get(application.id)
    assert saved_application is not None and saved_application.profile_id == other
