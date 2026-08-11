from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import SecretStr
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
    IntegrationProvider,
    MessageCategory,
    MutationAudit,
    MutationConfirmation,
    NormalizedMessage,
    OAuthAuthorizationRequest,
    OAuthAuthorizationState,
    OAuthCallbackResult,
    OutboundDraft,
    ProviderConfigurationImport,
    ProviderConfigurationSource,
    ProviderConfigurationStatus,
    ProviderMessageSyncResult,
    SchedulingPlanRequest,
    SchedulingRecommendation,
)
from job_apply_pro.integrations.communications import (
    CalendarProviderAdapter,
    MessageProviderAdapter,
    ProviderMutationError,
    ProviderNotConfiguredError,
)
from job_apply_pro.integrations.configuration import (
    CommunicationConfiguration,
    CommunicationConfigurationError,
    ProviderConnectionConfig,
    build_communication_configuration,
    summarize_communication_configuration,
)
from job_apply_pro.integrations.oauth import (
    OAUTH_PROVIDERS,
    OAuthAuthorizationError,
    OAuthConfigurationError,
    OAuthConnectionService,
)
from job_apply_pro.integrations.provider_clients import (
    GmailMessageProvider,
    GoogleCalendarProvider,
    OutlookCalendarProvider,
    OutlookMessageProvider,
)
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.services.communications import CommunicationService
from job_apply_pro.storage.communication_configuration_repository import (
    CommunicationConfigurationRepository,
)
from job_apply_pro.storage.communication_repository import CommunicationRepository
from job_apply_pro.storage.database import get_session
from job_apply_pro.storage.knowledge_repository import CandidateKnowledgeRepository
from job_apply_pro.storage.oauth_repository import OAuthRepository
from job_apply_pro.storage.repositories import WorkbenchRepository

router = APIRouter(prefix="/communications", tags=["communications"])
SessionDependency = Annotated[Session, Depends(get_session)]
CipherDependency = Annotated[SensitiveDataCipher, Depends(get_cipher)]


def _active_configuration(
    session: Session,
    cipher: SensitiveDataCipher,
) -> tuple[CommunicationConfiguration, ProviderConfigurationSource, datetime | None]:
    environment = get_settings().communication_config_json
    if environment is not None:
        return (
            build_communication_configuration(environment),
            ProviderConfigurationSource.ENVIRONMENT,
            None,
        )
    stored = CommunicationConfigurationRepository(session, cipher).load()
    if stored is not None:
        configuration, updated_at = stored
        return configuration, ProviderConfigurationSource.ENCRYPTED_DATABASE, updated_at
    return (
        build_communication_configuration(None),
        ProviderConfigurationSource.NOT_CONFIGURED,
        None,
    )


def _validated_import(raw: str) -> CommunicationConfiguration:
    configuration = build_communication_configuration(SecretStr(raw))
    if not configuration.providers and not configuration.oauth_clients:
        raise CommunicationConfigurationError(
            "Communication configuration must include at least one provider or OAuth client"
        )
    for client in configuration.oauth_clients:
        if not set(client.requested_scopes) <= OAUTH_PROVIDERS[client.provider].permitted_scopes:
            raise CommunicationConfigurationError(
                "Communication configuration includes a scope that is not approved for its provider"
            )
    return configuration


def get_communication_service(
    session: SessionDependency, cipher: CipherDependency
) -> CommunicationService:
    try:
        configuration, _, _ = _active_configuration(session, cipher)
    except CommunicationConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Communication provider configuration is invalid",
        ) from error
    clients = {item.provider: item for item in configuration.oauth_clients}
    oauth = OAuthConnectionService(OAuthRepository(session, cipher), clients)
    configured = {item.provider: item for item in configuration.providers}
    for provider, client in clients.items():
        state = oauth.state(provider)
        configured[provider] = ProviderConnectionConfig(
            provider=provider,
            credential_reference=state.credential_reference,
            account_hint=state.account_hint,
            granted_scopes=state.granted_scopes or client.requested_scopes,
            read_enabled=True,
            write_enabled=any(
                scope.endswith(
                    ("gmail.send", "Mail.Send", "calendar.events", "Calendars.ReadWrite")
                )
                for scope in (state.granted_scopes or client.requested_scopes)
            ),
        )
    message_adapters: dict[IntegrationProvider, MessageProviderAdapter] = {}
    calendar_adapters: dict[IntegrationProvider, CalendarProviderAdapter] = {}
    if (
        IntegrationProvider.GMAIL in clients
        and oauth.state(IntegrationProvider.GMAIL).status.value == "CONNECTED"
    ):
        message_adapters[IntegrationProvider.GMAIL] = GmailMessageProvider(oauth)
    if (
        IntegrationProvider.OUTLOOK in clients
        and oauth.state(IntegrationProvider.OUTLOOK).status.value == "CONNECTED"
    ):
        message_adapters[IntegrationProvider.OUTLOOK] = OutlookMessageProvider(oauth)
    if (
        IntegrationProvider.GOOGLE_CALENDAR in clients
        and oauth.state(IntegrationProvider.GOOGLE_CALENDAR).status.value == "CONNECTED"
    ):
        calendar_adapters[IntegrationProvider.GOOGLE_CALENDAR] = GoogleCalendarProvider(oauth)
    if (
        IntegrationProvider.OUTLOOK_CALENDAR in clients
        and oauth.state(IntegrationProvider.OUTLOOK_CALENDAR).status.value == "CONNECTED"
    ):
        calendar_adapters[IntegrationProvider.OUTLOOK_CALENDAR] = OutlookCalendarProvider(oauth)
    return CommunicationService(
        CommunicationRepository(session, cipher),
        message_adapters=message_adapters or None,
        calendar_adapters=calendar_adapters or None,
        automatic_categories=configuration.automatic_categories,
        provider_configs=configured,
        knowledge_repository=CandidateKnowledgeRepository(session),
    )


ServiceDependency = Annotated[CommunicationService, Depends(get_communication_service)]


def get_oauth_service(
    session: SessionDependency, cipher: CipherDependency
) -> OAuthConnectionService:
    try:
        configuration, _, _ = _active_configuration(session, cipher)
    except CommunicationConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Communication provider configuration is invalid",
        ) from error
    return OAuthConnectionService(
        OAuthRepository(session, cipher),
        {item.provider: item for item in configuration.oauth_clients},
    )


OAuthServiceDependency = Annotated[OAuthConnectionService, Depends(get_oauth_service)]


@router.get("/configuration", response_model=ProviderConfigurationStatus)
def provider_configuration_status(
    session: SessionDependency,
    cipher: CipherDependency,
) -> ProviderConfigurationStatus:
    try:
        configuration, source, updated_at = _active_configuration(session, cipher)
    except CommunicationConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Communication provider configuration is invalid",
        ) from error
    return summarize_communication_configuration(
        configuration,
        source=source,
        updated_at=updated_at,
    )


@router.post("/configuration/validate", response_model=ProviderConfigurationStatus)
def validate_provider_configuration(
    command: ProviderConfigurationImport,
) -> ProviderConfigurationStatus:
    try:
        configuration = _validated_import(command.configuration_json.get_secret_value())
    except CommunicationConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    return summarize_communication_configuration(
        configuration,
        source=ProviderConfigurationSource.IMPORT_PREVIEW,
    )


@router.post("/configuration/import", response_model=ProviderConfigurationStatus)
def import_provider_configuration(
    command: ProviderConfigurationImport,
    session: SessionDependency,
    cipher: CipherDependency,
) -> ProviderConfigurationStatus:
    if get_settings().communication_config_json is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Provider configuration is managed by the process environment",
        )
    try:
        configuration = _validated_import(command.configuration_json.get_secret_value())
    except CommunicationConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    updated_at = CommunicationConfigurationRepository(session, cipher).save(configuration)
    return summarize_communication_configuration(
        configuration,
        source=ProviderConfigurationSource.ENCRYPTED_DATABASE,
        updated_at=updated_at,
    )


@router.delete("/configuration", response_model=ProviderConfigurationStatus)
def clear_provider_configuration(
    session: SessionDependency,
    cipher: CipherDependency,
) -> ProviderConfigurationStatus:
    if get_settings().communication_config_json is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Provider configuration is managed by the process environment",
        )
    CommunicationConfigurationRepository(session, cipher).delete()
    return summarize_communication_configuration(
        CommunicationConfiguration(),
        source=ProviderConfigurationSource.NOT_CONFIGURED,
    )


@router.get("/integrations", response_model=list[IntegrationHealth])
def integration_health(service: ServiceDependency) -> list[IntegrationHealth]:
    return service.health()


@router.post(
    "/oauth/{provider}/start",
    response_model=OAuthAuthorizationRequest,
    status_code=status.HTTP_201_CREATED,
)
def start_oauth(
    provider: IntegrationProvider, service: OAuthServiceDependency
) -> OAuthAuthorizationRequest:
    try:
        return service.start(provider)
    except OAuthConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
        ) from error


@router.get("/oauth/callback", response_model=OAuthCallbackResult)
def oauth_callback(
    code: Annotated[str, Query(min_length=1, max_length=4_000)],
    state: Annotated[str, Query(min_length=32, max_length=200)],
    service: OAuthServiceDependency,
) -> OAuthCallbackResult:
    try:
        return service.complete(code=code, state=state)
    except OAuthAuthorizationError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


@router.get("/oauth/{provider}", response_model=OAuthAuthorizationState)
def oauth_state(
    provider: IntegrationProvider, service: OAuthServiceDependency
) -> OAuthAuthorizationState:
    return service.state(provider)


@router.post("/oauth/{provider}/revoke", response_model=OAuthAuthorizationState)
def revoke_oauth(
    provider: IntegrationProvider, service: OAuthServiceDependency
) -> OAuthAuthorizationState:
    try:
        return service.revoke(provider)
    except OAuthAuthorizationError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error


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


@router.post(
    "/providers/{provider}/messages/sync",
    response_model=ProviderMessageSyncResult,
)
def sync_provider_messages(
    provider: IntegrationProvider,
    service: ServiceDependency,
    session: SessionDependency,
    since: Annotated[datetime | None, Query()] = None,
) -> ProviderMessageSyncResult:
    try:
        return service.sync_provider_messages(
            provider,
            since=since,
            workflows=WorkbenchRepository(session).list_snapshots(),
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error
    except ProviderNotConfiguredError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
        ) from error
    except ProviderMutationError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error


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
