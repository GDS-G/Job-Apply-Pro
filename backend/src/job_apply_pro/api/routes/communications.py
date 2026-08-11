from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from job_apply_pro.api.routes.core import get_cipher
from job_apply_pro.config import get_settings
from job_apply_pro.domain.communications import (
    ApplicationCommunicationStatus,
    AttachmentCandidate,
    AttachmentVerification,
    CalendarMutationCreate,
    CalendarMutationPlan,
    CommunicationExport,
    CommunicationRecord,
    DailyCommunicationSummary,
    DraftCreate,
    FollowUp,
    FollowUpCreate,
    IntegrationHealth,
    MessageCategory,
    MutationAudit,
    MutationConfirmation,
    NormalizedMessage,
    OutboundDraft,
    SchedulingPlanRequest,
    SchedulingRecommendation,
)
from job_apply_pro.integrations.communications import ProviderNotConfiguredError
from job_apply_pro.integrations.configuration import (
    CommunicationConfigurationError,
    build_communication_configuration,
)
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.services.communications import CommunicationService
from job_apply_pro.storage.communication_repository import CommunicationRepository
from job_apply_pro.storage.database import get_session
from job_apply_pro.storage.knowledge_repository import CandidateKnowledgeRepository
from job_apply_pro.storage.repositories import WorkbenchRepository

router = APIRouter(prefix="/communications", tags=["communications"])
SessionDependency = Annotated[Session, Depends(get_session)]
CipherDependency = Annotated[SensitiveDataCipher, Depends(get_cipher)]


def get_communication_service(
    session: SessionDependency, cipher: CipherDependency
) -> CommunicationService:
    try:
        configuration = build_communication_configuration(get_settings().communication_config_json)
    except CommunicationConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Communication provider configuration is invalid",
        ) from error
    return CommunicationService(
        CommunicationRepository(session, cipher),
        automatic_categories=configuration.automatic_categories,
        provider_configs={item.provider: item for item in configuration.providers},
        knowledge_repository=CandidateKnowledgeRepository(session),
    )


ServiceDependency = Annotated[CommunicationService, Depends(get_communication_service)]


@router.get("/integrations", response_model=list[IntegrationHealth])
def integration_health(service: ServiceDependency) -> list[IntegrationHealth]:
    return service.health()


@router.post("/analyze", response_model=CommunicationRecord, status_code=201)
def analyze_message(
    message: NormalizedMessage,
    service: ServiceDependency,
    session: SessionDependency,
) -> CommunicationRecord:
    return service.analyze_and_save(message, WorkbenchRepository(session).list_snapshots())


@router.get("/records", response_model=list[CommunicationRecord])
def list_communication_records(
    service: ServiceDependency,
    query: Annotated[str | None, Query(max_length=500)] = None,
    category: MessageCategory | None = None,
    workflow_id: Annotated[str | None, Query(max_length=100)] = None,
) -> list[CommunicationRecord]:
    return service.search_records(query=query, category=category, workflow_id=workflow_id)


@router.post("/drafts", response_model=OutboundDraft, status_code=201)
def create_outbound_draft(command: DraftCreate, service: ServiceDependency) -> OutboundDraft:
    try:
        return service.create_draft(command)
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error


@router.get("/drafts", response_model=list[OutboundDraft])
def list_outbound_drafts(service: ServiceDependency) -> list[OutboundDraft]:
    return service.list_drafts()


@router.post("/drafts/{draft_id}/send", response_model=MutationAudit)
def send_outbound_draft(
    draft_id: str, command: MutationConfirmation, service: ServiceDependency
) -> MutationAudit:
    try:
        return service.send_draft(draft_id, command)
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except ProviderNotConfiguredError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
        ) from error


@router.post("/calendar/plans", response_model=CalendarMutationPlan, status_code=201)
def create_calendar_plan(
    command: CalendarMutationCreate, service: ServiceDependency
) -> CalendarMutationPlan:
    try:
        return service.plan_calendar_mutation(command)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error


@router.post("/calendar/plans/{plan_id}/execute", response_model=MutationAudit)
def execute_calendar_plan(
    plan_id: str, command: MutationConfirmation, service: ServiceDependency
) -> MutationAudit:
    try:
        return service.execute_calendar_mutation(plan_id, command)
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except ProviderNotConfiguredError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
        ) from error


@router.get("/mutation-audits", response_model=list[MutationAudit])
def list_mutation_audits(service: ServiceDependency) -> list[MutationAudit]:
    return service.list_audits()


@router.post("/follow-ups", response_model=FollowUp, status_code=201)
def create_follow_up(command: FollowUpCreate, service: ServiceDependency) -> FollowUp:
    return service.schedule_follow_up(command)


@router.get("/follow-ups", response_model=list[FollowUp])
def list_follow_ups(service: ServiceDependency) -> list[FollowUp]:
    return service.list_follow_ups()


@router.get("/daily-summary", response_model=DailyCommunicationSummary)
def daily_summary(service: ServiceDependency) -> DailyCommunicationSummary:
    return service.daily_summary()


@router.get("/export", response_model=CommunicationExport)
def export_communications(service: ServiceDependency) -> CommunicationExport:
    return service.export()


@router.get("/tracking", response_model=list[ApplicationCommunicationStatus])
def communication_tracking(service: ServiceDependency) -> list[ApplicationCommunicationStatus]:
    return service.tracking_statuses()


@router.post(
    "/profiles/{profile_id}/attachments/verify",
    response_model=AttachmentVerification,
)
def verify_attachment(
    profile_id: str, candidate: AttachmentCandidate, service: ServiceDependency
) -> AttachmentVerification:
    return service.verify_attachment(candidate, expected_profile_id=profile_id)


@router.post("/calendar/rank-times", response_model=list[SchedulingRecommendation])
def rank_calendar_times(
    plan: SchedulingPlanRequest, service: ServiceDependency
) -> list[SchedulingRecommendation]:
    return service.rank_times(plan.request, plan.events)
