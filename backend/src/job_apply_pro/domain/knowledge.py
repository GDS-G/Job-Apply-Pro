from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class DocumentKind(StrEnum):
    RESUME = "RESUME"
    COVER_LETTER = "COVER_LETTER"
    CERTIFICATION = "CERTIFICATION"
    EDUCATION = "EDUCATION"
    PORTFOLIO = "PORTFOLIO"
    OTHER = "OTHER"


class DocumentOutputFormat(StrEnum):
    DOCX = "DOCX"
    PDF = "PDF"


class ClaimVerificationStatus(StrEnum):
    PROPOSED = "PROPOSED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class ClaimPermittedUse(StrEnum):
    PROFILE_ONLY = "PROFILE_ONLY"
    APPLICATIONS = "APPLICATIONS"
    ANY = "ANY"


class SensitivityLevel(StrEnum):
    PUBLIC = "PUBLIC"
    PERSONAL = "PERSONAL"
    SENSITIVE = "SENSITIVE"


class ClaimType(StrEnum):
    IDENTITY = "IDENTITY"
    CONTACT = "CONTACT"
    SKILL = "SKILL"
    EXPERIENCE = "EXPERIENCE"
    EDUCATION = "EDUCATION"
    CERTIFICATION = "CERTIFICATION"
    PREFERENCE = "PREFERENCE"
    OTHER = "OTHER"


class LayoutBlock(BaseModel):
    model_config = ConfigDict(frozen=True)

    index: int = Field(ge=0)
    page: int | None = Field(default=None, ge=1)
    row: int | None = Field(default=None, ge=0)
    column: int | None = Field(default=None, ge=0)
    table: int | None = Field(default=None, ge=0)
    kind: str = Field(min_length=1, max_length=40)
    style: str | None = Field(default=None, max_length=100)
    text: str = Field(max_length=20_000)


class DocumentExtraction(BaseModel):
    model_config = ConfigDict(frozen=True)

    parser: str
    plain_text: str = Field(max_length=200_000)
    blocks: list[LayoutBlock] = Field(max_length=5_000)
    page_count: int = Field(ge=1, le=500)
    character_count: int = Field(ge=0, le=200_000)
    warnings: list[str] = Field(default_factory=list, max_length=100)


class CandidateDocument(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    profile_id: str
    kind: DocumentKind
    display_name: str
    variant_label: str
    job_family_tags: list[str]
    is_primary: bool
    archived: bool
    created_at: datetime


class CandidateDocumentVersion(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    document_id: str
    version: int = Field(ge=1)
    file_name: str
    media_type: str
    sha256: str = Field(min_length=64, max_length=64)
    parser_version: str
    page_count: int = Field(ge=1)
    character_count: int = Field(ge=0)
    created_at: datetime


class CandidateDocumentVersionRecord(CandidateDocumentVersion):
    model_config = ConfigDict(frozen=True)

    storage_path: str
    encrypted_extraction: str


class EvidenceSource(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    profile_id: str
    document_version_id: str | None = None
    source_type: str
    source_label: str
    source_uri: str | None = None
    content_hash: str
    created_at: datetime


class CandidateClaim(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    profile_id: str
    evidence_source_id: str | None = None
    canonical_key: str = Field(min_length=1, max_length=160)
    statement: str = Field(min_length=1, max_length=2_000)
    claim_type: ClaimType
    value: dict[str, object]
    source_location: str | None = Field(default=None, max_length=500)
    context: dict[str, object] = Field(default_factory=dict)
    start_date: date | None = None
    end_date: date | None = None
    confidence: float = Field(ge=0, le=1)
    verification_status: ClaimVerificationStatus
    permitted_use: ClaimPermittedUse
    sensitivity: SensitivityLevel
    locked: bool
    superseded_by_id: str | None = None
    created_at: datetime
    updated_at: datetime


class ClaimReview(BaseModel):
    model_config = ConfigDict(frozen=True)

    approved: bool
    statement: str | None = Field(default=None, min_length=1, max_length=2_000)
    value: dict[str, object] | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    permitted_use: ClaimPermittedUse | None = None
    sensitivity: SensitivityLevel | None = None
    lock: bool = True


class DocumentImportResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    document: CandidateDocument
    version: CandidateDocumentVersion
    extraction: DocumentExtraction
    proposed_claims: list[CandidateClaim]


class TailoredDocumentRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    application_id: str = Field(min_length=1, max_length=100)
    kind: DocumentKind
    output_format: DocumentOutputFormat = DocumentOutputFormat.DOCX
    variant_label: str = Field(default="Tailored", min_length=1, max_length=120)
    max_claims: int = Field(default=12, ge=1, le=30)


class TailoredDocumentSection(BaseModel):
    model_config = ConfigDict(frozen=True)

    heading: str = Field(min_length=1, max_length=200)
    paragraphs: list[str] = Field(max_length=50)
    evidence_claim_ids: list[str] = Field(default_factory=list, max_length=50)


class TailoredDocumentPreview(BaseModel):
    model_config = ConfigDict(frozen=True)

    application_id: str
    profile_id: str
    job_id: str
    kind: DocumentKind
    output_format: DocumentOutputFormat
    employer: str
    title: str
    variant_label: str
    sections: list[TailoredDocumentSection]
    selected_claim_ids: list[str]
    matched_requirement_ids: list[str]
    missing_required_requirements: list[str]
    review_fingerprint: str = Field(min_length=64, max_length=64)


class TailoredDocumentApproval(TailoredDocumentRequest):
    model_config = ConfigDict(frozen=True)

    review_fingerprint: str = Field(min_length=64, max_length=64)
    confirmation_phrase: str = Field(min_length=1, max_length=100)


class DocumentGenerationAudit(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    application_id: str
    profile_id: str
    job_id: str
    document_version_id: str
    kind: DocumentKind
    output_format: DocumentOutputFormat
    review_fingerprint: str
    evidence_claim_ids: list[str]
    requirement_ids: list[str]
    missing_required_requirements: list[str]
    created_at: datetime


class TailoredDocumentResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    preview: TailoredDocumentPreview
    document: CandidateDocument
    version: CandidateDocumentVersion
    audit: DocumentGenerationAudit


class ExperienceSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    skill: str
    months: int = Field(ge=0)
    years: float = Field(ge=0)
    supporting_claim_ids: list[str]


class AnswerLibraryCreate(BaseModel):
    model_config = ConfigDict(frozen=True)

    question: str = Field(min_length=1, max_length=2_000)
    canonical_field: str = Field(min_length=1, max_length=160)
    answer: str = Field(min_length=1, max_length=20_000)
    evidence_claim_ids: list[str] = Field(default_factory=list, max_length=50)
    confidence: float = Field(default=1, ge=0, le=1)
    approved: bool = True
    locked: bool = True
    reuse_permission: ClaimPermittedUse = ClaimPermittedUse.APPLICATIONS
    provenance: dict[str, object] = Field(default_factory=dict)


class AnswerLibraryEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    profile_id: str
    question: str
    canonical_field: str
    answer: str
    evidence_claim_ids: list[str]
    confidence: float
    approved: bool
    locked: bool
    reuse_permission: ClaimPermittedUse
    provenance: dict[str, object]
    created_at: datetime
    updated_at: datetime


class AnswerLibraryRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    profile_id: str
    canonical_field: str
    encrypted_question: str
    encrypted_answer: str
    evidence_claim_ids: list[str]
    confidence: float
    approved: bool
    locked: bool
    reuse_permission: ClaimPermittedUse
    provenance: dict[str, object]
    created_at: datetime
    updated_at: datetime


class RetrievalChunkRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    profile_id: str
    source_type: str
    source_id: str
    canonical_key: str
    encrypted_content: str
    token_hashes: list[str]
    vector: list[float]
    permitted_use: ClaimPermittedUse
    evidence_claim_ids: list[str]
    provenance: dict[str, object]
    created_at: datetime
    updated_at: datetime


class RetrievalQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    query: str = Field(min_length=1, max_length=2_000)
    permitted_use: ClaimPermittedUse = ClaimPermittedUse.APPLICATIONS
    limit: int = Field(default=5, ge=1, le=20)


class RetrievalResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_type: str
    source_id: str
    canonical_key: str
    content: str
    score: float = Field(ge=0, le=1)
    evidence_claim_ids: list[str]
    provenance: dict[str, object]


class CandidateKnowledgeSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    profile_id: str
    documents: list[CandidateDocument]
    claims: list[CandidateClaim]
    answers: list[AnswerLibraryEntry]
