from sqlalchemy.orm import Session

from job_apply_pro.domain.candidate import CandidateProfileCreate, ContactDetails
from job_apply_pro.domain.workbench import (
    MockWorkflowCreate,
    WorkflowControlAction,
    WorkflowControlCommand,
)
from job_apply_pro.domain.workflow import WorkflowState
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.security.keys import StaticKeyProvider
from job_apply_pro.services.core import CoreService
from job_apply_pro.services.workbench import WorkbenchService
from job_apply_pro.storage.repositories import (
    ApplicationRepository,
    CandidateRepository,
    CheckpointRepository,
    JobRepository,
    WorkbenchRepository,
)


def _core(session: Session) -> CoreService:
    return CoreService(
        CandidateRepository(session),
        JobRepository(session),
        ApplicationRepository(session),
        CheckpointRepository(session),
        SensitiveDataCipher(StaticKeyProvider(b"w" * 32)),
    )


def _workbench(session: Session) -> WorkbenchService:
    return WorkbenchService(
        CandidateRepository(session),
        JobRepository(session),
        ApplicationRepository(session),
        WorkbenchRepository(session),
    )


def test_mock_workflow_controls_and_restart_recovery(session: Session) -> None:
    profile = _core(session).create_candidate(
        CandidateProfileCreate(
            display_name="Workbench profile",
            contact=ContactDetails(
                full_name="Workbench User",
                email="workbench@example.com",
            ),
        )
    )
    service = _workbench(session)
    started = service.start_mock_workflow(
        MockWorkflowCreate(
            profile_id=profile.id,
            employer="Workbench Labs",
            title="Desktop Engineer",
        )
    )
    assert started.state is WorkflowState.DEDUPLICATED
    assert started.events[-1].sequence == 1

    paused = service.control_workflow(
        started.workflow_id,
        WorkflowControlCommand(action=WorkflowControlAction.PAUSE),
    )
    assert paused.state is WorkflowState.USER_TAKEOVER

    session.close()
    with Session(session.get_bind()) as restarted_session:
        recovered = _workbench(restarted_session).get_workflow(started.workflow_id)
        assert recovered.state is WorkflowState.USER_TAKEOVER
        assert [event.sequence for event in recovered.events] == [1, 2]

        resumed = _workbench(restarted_session).control_workflow(
            started.workflow_id,
            WorkflowControlCommand(action=WorkflowControlAction.RESUME),
        )
        advanced = _workbench(restarted_session).control_workflow(
            started.workflow_id,
            WorkflowControlCommand(action=WorkflowControlAction.ADVANCE),
        )
        assert resumed.state is WorkflowState.DEDUPLICATED
        assert advanced.state is WorkflowState.SCORED
        assert len(advanced.events) == 4
