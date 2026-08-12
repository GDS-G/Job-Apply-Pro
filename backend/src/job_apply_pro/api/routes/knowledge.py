from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy.orm import Session

from job_apply_pro.ai.configuration import build_ai_registry
from job_apply_pro.api.routes.core import get_cipher
from job_apply_pro.config import get_settings
from job_apply_pro.documents.extractors import DocumentExtractionError, DocumentIngestionOptions
from job_apply_pro.domain.applications import (
    SubmittedDocumentCapture,
    SubmittedDocumentEvidence,
)
from job_apply_pro.domain.knowledge import (
    AnswerLibraryCreate,
    AnswerLibraryEntry,
    CandidateClaim,
    CandidateDocument,
    CandidateDocumentVersion,
    CandidateKnowledgeSnapshot,
    ClaimReview,
    DocumentExtraction,
    DocumentGenerationAudit,
    DocumentImportResult,
    DocumentKind,
    DocumentSelectionApproval,
    DocumentSelectionAudit,
    DocumentSelectionPreview,
    DocumentSelectionRequest,
    ExperienceSummary,
    RetrievalQuery,
    RetrievalResult,
    TailoredDocumentApproval,
    TailoredDocumentPreview,
    TailoredDocumentRequest,
    TailoredDocumentResult,
)
from job_apply_pro.security.encryption import DecryptionError, SensitiveDataCipher
from job_apply_pro.security.keys import KeyConfigurationError
from job_apply_pro.services.ai import AIGatewayService
from job_apply_pro.services.knowledge import (
    CandidateKnowledgeConflictError,
    CandidateKnowledgeError,
    CandidateKnowledgeService,
)
from job_apply_pro.storage.ai_repository import AIGatewayRepository
from job_apply_pro.storage.database import get_session
from job_apply_pro.storage.knowledge_repository import CandidateKnowledgeRepository
from job_apply_pro.storage.repositories import (
    ApplicationRepository,
    CandidateRepository,
    JobRepository,
)

router = APIRouter(prefix="/knowledge", tags=["candidate-knowledge"])
SessionDependency = Annotated[Session, Depends(get_session)]
CipherDependency = Annotated[SensitiveDataCipher, Depends(get_cipher)]


def get_knowledge_service(
    session: SessionDependency, cipher: CipherDependency
) -> CandidateKnowledgeService:
    settings = get_settings()
    return CandidateKnowledgeService(
        CandidateKnowledgeRepository(session),
        CandidateRepository(session),
        JobRepository(session),
        ApplicationRepository(session),
        cipher,
        document_data_dir=settings.document_data_dir,
        document_max_bytes=settings.document_max_bytes,
        document_ingestion_options=DocumentIngestionOptions(
            legacy_doc_converter_path=settings.document_legacy_converter_path,
            legacy_doc_conversion_timeout_seconds=settings.document_conversion_timeout_seconds,
            max_converted_bytes=settings.document_max_bytes,
            ocr_enabled=settings.document_ocr_enabled,
            ocr_tesseract_path=settings.document_ocr_tesseract_path,
            ocr_language=settings.document_ocr_language,
            ocr_dpi=settings.document_ocr_dpi,
            ocr_max_pages=settings.document_ocr_max_pages,
            ocr_page_timeout_seconds=settings.document_ocr_page_timeout_seconds,
        ),
        ai_gateway=AIGatewayService(
            build_ai_registry(settings.ai_config_json), AIGatewayRepository(session), cipher
        ),
    )


KnowledgeServiceDependency = Annotated[CandidateKnowledgeService, Depends(get_knowledge_service)]


def _http_error(error: Exception) -> HTTPException:
    if isinstance(error, LookupError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    if isinstance(error, CandidateKnowledgeConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    if isinstance(error, (CandidateKnowledgeError, DocumentExtractionError)):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error))
    if isinstance(error, (KeyConfigurationError, DecryptionError)):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Candidate knowledge encryption is unavailable",
        )
    raise error


@router.post(
    "/profiles/{profile_id}/documents",
    response_model=DocumentImportResult,
    status_code=status.HTTP_201_CREATED,
)
async def import_candidate_document(
    profile_id: str,
    service: KnowledgeServiceDependency,
    file: Annotated[UploadFile, File()],
    kind: Annotated[DocumentKind, Form()] = DocumentKind.RESUME,
    display_name: Annotated[str, Form(min_length=1, max_length=200)] = "Imported resume",
    variant_label: Annotated[str, Form(min_length=1, max_length=120)] = "General",
    job_family_tags: Annotated[str, Form(max_length=1_000)] = "",
    is_primary: Annotated[bool, Form()] = False,
) -> DocumentImportResult:
    settings = get_settings()
    data = await file.read(settings.document_max_bytes + 1)
    try:
        return service.import_document(
            profile_id,
            file_name=file.filename or "document",
            data=data,
            kind=kind,
            display_name=display_name,
            variant_label=variant_label,
            job_family_tags=job_family_tags.split(","),
            is_primary=is_primary,
        )
    except (
        LookupError,
        CandidateKnowledgeError,
        CandidateKnowledgeConflictError,
        DocumentExtractionError,
        KeyConfigurationError,
        DecryptionError,
    ) as error:
        raise _http_error(error) from error


@router.get("/profiles/{profile_id}/documents", response_model=list[CandidateDocument])
def list_candidate_documents(
    profile_id: str, service: KnowledgeServiceDependency
) -> list[CandidateDocument]:
    try:
        return service.list_documents(profile_id)
    except LookupError as error:
        raise _http_error(error) from error


@router.post("/documents/selection/preview", response_model=DocumentSelectionPreview)
def preview_document_selection(
    command: DocumentSelectionRequest, service: KnowledgeServiceDependency
) -> DocumentSelectionPreview:
    try:
        return service.preview_document_selection(command)
    except (
        LookupError,
        CandidateKnowledgeError,
        CandidateKnowledgeConflictError,
        KeyConfigurationError,
        DecryptionError,
    ) as error:
        raise _http_error(error) from error


@router.post("/documents/selection/approve", response_model=DocumentSelectionAudit)
def approve_document_selection(
    command: DocumentSelectionApproval, service: KnowledgeServiceDependency
) -> DocumentSelectionAudit:
    try:
        return service.approve_document_selection(command)
    except (
        LookupError,
        CandidateKnowledgeError,
        CandidateKnowledgeConflictError,
        KeyConfigurationError,
        DecryptionError,
    ) as error:
        raise _http_error(error) from error


@router.get(
    "/applications/{application_id}/document-selections",
    response_model=list[DocumentSelectionAudit],
)
def list_document_selection_audits(
    application_id: str, service: KnowledgeServiceDependency
) -> list[DocumentSelectionAudit]:
    try:
        return service.list_document_selection_audits(application_id)
    except LookupError as error:
        raise _http_error(error) from error


@router.get("/documents/{document_id}/versions", response_model=list[CandidateDocumentVersion])
def list_document_versions(
    document_id: str, service: KnowledgeServiceDependency
) -> list[CandidateDocumentVersion]:
    try:
        return service.list_versions(document_id)
    except LookupError as error:
        raise _http_error(error) from error


@router.get("/document-versions/{version_id}/extraction", response_model=DocumentExtraction)
def get_document_extraction(
    version_id: str, service: KnowledgeServiceDependency
) -> DocumentExtraction:
    try:
        return service.get_extraction(version_id)
    except (LookupError, KeyConfigurationError, DecryptionError) as error:
        raise _http_error(error) from error


@router.get("/document-versions/{version_id}/content", response_class=Response)
def get_document_content(version_id: str, service: KnowledgeServiceDependency) -> Response:
    try:
        return Response(
            content=service.get_document_content(version_id),
            media_type="application/octet-stream",
            headers={"X-Content-Type-Options": "nosniff"},
        )
    except (
        LookupError,
        CandidateKnowledgeError,
        KeyConfigurationError,
        DecryptionError,
    ) as error:
        raise _http_error(error) from error


@router.get("/profiles/{profile_id}/claims", response_model=list[CandidateClaim])
def list_candidate_claims(
    profile_id: str, service: KnowledgeServiceDependency
) -> list[CandidateClaim]:
    try:
        return service.list_claims(profile_id)
    except LookupError as error:
        raise _http_error(error) from error


@router.post("/claims/{claim_id}/review", response_model=CandidateClaim)
def review_candidate_claim(
    claim_id: str, command: ClaimReview, service: KnowledgeServiceDependency
) -> CandidateClaim:
    try:
        return service.review_claim(claim_id, command)
    except (LookupError, CandidateKnowledgeConflictError) as error:
        raise _http_error(error) from error


@router.get("/profiles/{profile_id}/experience", response_model=list[ExperienceSummary])
def calculate_candidate_experience(
    profile_id: str, service: KnowledgeServiceDependency
) -> list[ExperienceSummary]:
    try:
        return service.calculate_experience(profile_id)
    except LookupError as error:
        raise _http_error(error) from error


@router.post(
    "/profiles/{profile_id}/answers",
    response_model=AnswerLibraryEntry,
    status_code=status.HTTP_201_CREATED,
)
def add_answer_library_entry(
    profile_id: str,
    command: AnswerLibraryCreate,
    service: KnowledgeServiceDependency,
) -> AnswerLibraryEntry:
    try:
        return service.add_answer(profile_id, command)
    except (
        LookupError,
        CandidateKnowledgeConflictError,
        KeyConfigurationError,
        DecryptionError,
    ) as error:
        raise _http_error(error) from error


@router.get("/profiles/{profile_id}/answers", response_model=list[AnswerLibraryEntry])
def list_answer_library(
    profile_id: str, service: KnowledgeServiceDependency
) -> list[AnswerLibraryEntry]:
    try:
        return service.list_answers(profile_id)
    except (LookupError, KeyConfigurationError, DecryptionError) as error:
        raise _http_error(error) from error


@router.post("/profiles/{profile_id}/retrieve", response_model=list[RetrievalResult])
def retrieve_candidate_knowledge(
    profile_id: str,
    command: RetrievalQuery,
    service: KnowledgeServiceDependency,
) -> list[RetrievalResult]:
    try:
        return service.retrieve(profile_id, command)
    except (LookupError, KeyConfigurationError, DecryptionError) as error:
        raise _http_error(error) from error


@router.get("/profiles/{profile_id}/snapshot", response_model=CandidateKnowledgeSnapshot)
def get_candidate_knowledge_snapshot(
    profile_id: str, service: KnowledgeServiceDependency
) -> CandidateKnowledgeSnapshot:
    try:
        return service.snapshot(profile_id)
    except (LookupError, KeyConfigurationError, DecryptionError) as error:
        raise _http_error(error) from error


@router.post(
    "/documents/tailored/preview",
    response_model=TailoredDocumentPreview,
)
def preview_tailored_document(
    command: TailoredDocumentRequest,
    service: KnowledgeServiceDependency,
) -> TailoredDocumentPreview:
    try:
        return service.preview_tailored_document(command)
    except (
        LookupError,
        CandidateKnowledgeError,
        CandidateKnowledgeConflictError,
        KeyConfigurationError,
        DecryptionError,
    ) as error:
        raise _http_error(error) from error


@router.post(
    "/documents/tailored/generate",
    response_model=TailoredDocumentResult,
    status_code=status.HTTP_201_CREATED,
)
def generate_tailored_document(
    approval: TailoredDocumentApproval,
    service: KnowledgeServiceDependency,
) -> TailoredDocumentResult:
    try:
        return service.generate_tailored_document(approval)
    except (
        LookupError,
        CandidateKnowledgeError,
        CandidateKnowledgeConflictError,
        KeyConfigurationError,
        DecryptionError,
    ) as error:
        raise _http_error(error) from error


@router.get(
    "/applications/{application_id}/document-generation-audits",
    response_model=list[DocumentGenerationAudit],
)
def list_document_generation_audits(
    application_id: str,
    service: KnowledgeServiceDependency,
) -> list[DocumentGenerationAudit]:
    try:
        return service.list_generation_audits(application_id)
    except LookupError as error:
        raise _http_error(error) from error


@router.post(
    "/applications/{application_id}/submitted-documents",
    response_model=SubmittedDocumentEvidence,
    status_code=status.HTTP_201_CREATED,
)
def capture_submitted_document(
    application_id: str,
    command: SubmittedDocumentCapture,
    service: KnowledgeServiceDependency,
) -> SubmittedDocumentEvidence:
    try:
        return service.capture_submitted_document(application_id, command)
    except (
        LookupError,
        CandidateKnowledgeError,
        CandidateKnowledgeConflictError,
    ) as error:
        raise _http_error(error) from error


@router.get(
    "/applications/{application_id}/submitted-documents",
    response_model=list[SubmittedDocumentEvidence],
)
def list_submitted_documents(
    application_id: str,
    service: KnowledgeServiceDependency,
) -> list[SubmittedDocumentEvidence]:
    try:
        return service.list_submitted_documents(application_id)
    except LookupError as error:
        raise _http_error(error) from error
