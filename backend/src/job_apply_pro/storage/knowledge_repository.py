from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_apply_pro.domain.applications import (
    ApplicationDocumentRole,
    SubmittedDocumentEvidence,
)
from job_apply_pro.domain.knowledge import (
    AnswerLibraryRecord,
    CandidateClaim,
    CandidateDocument,
    CandidateDocumentVersion,
    CandidateDocumentVersionRecord,
    ClaimPermittedUse,
    ClaimType,
    ClaimVerificationStatus,
    DocumentGenerationAudit,
    DocumentKind,
    DocumentOutputFormat,
    EvidenceSource,
    RetrievalChunkRecord,
    SensitivityLevel,
)
from job_apply_pro.storage.models import (
    AnswerLibraryRow,
    CandidateClaimRow,
    DocumentGenerationAuditRow,
    DocumentRow,
    DocumentVersionRow,
    EvidenceSourceRow,
    RetrievalChunkRow,
    SubmittedDocumentEvidenceRow,
)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _document(row: DocumentRow) -> CandidateDocument:
    return CandidateDocument(
        id=row.id,
        profile_id=row.profile_id,
        kind=DocumentKind(row.kind),
        display_name=row.display_name,
        variant_label=row.variant_label,
        job_family_tags=row.job_family_tags_json,
        is_primary=row.is_primary,
        archived=row.archived,
        created_at=_utc(row.created_at),
    )


def _version(row: DocumentVersionRow) -> CandidateDocumentVersionRecord:
    return CandidateDocumentVersionRecord(
        id=row.id,
        document_id=row.document_id,
        version=row.version,
        file_name=row.file_name,
        media_type=row.media_type,
        sha256=row.sha256,
        parser_version=row.parser_version,
        page_count=row.page_count,
        character_count=row.character_count,
        created_at=_utc(row.created_at),
        storage_path=row.storage_path,
        encrypted_extraction=row.encrypted_extraction,
    )


def _claim(row: CandidateClaimRow) -> CandidateClaim:
    return CandidateClaim(
        id=row.id,
        profile_id=row.profile_id,
        evidence_source_id=row.evidence_source_id,
        canonical_key=row.canonical_key,
        statement=row.statement,
        claim_type=ClaimType(row.claim_type),
        value=row.value_json,
        source_location=row.source_location,
        context=row.context_json,
        start_date=row.start_date,
        end_date=row.end_date,
        confidence=row.confidence,
        verification_status=ClaimVerificationStatus(row.verification_status),
        permitted_use=ClaimPermittedUse(row.permitted_use),
        sensitivity=SensitivityLevel(row.sensitivity),
        locked=row.locked,
        superseded_by_id=row.superseded_by_id,
        created_at=_utc(row.created_at),
        updated_at=_utc(row.updated_at),
    )


def _answer(row: AnswerLibraryRow) -> AnswerLibraryRecord:
    return AnswerLibraryRecord(
        id=row.id,
        profile_id=row.profile_id,
        canonical_field=row.canonical_field,
        encrypted_question=row.encrypted_question,
        encrypted_answer=row.encrypted_answer,
        evidence_claim_ids=row.evidence_claim_ids_json,
        confidence=row.confidence,
        approved=row.approved,
        locked=row.locked,
        reuse_permission=ClaimPermittedUse(row.reuse_permission),
        provenance=row.provenance_json,
        created_at=_utc(row.created_at),
        updated_at=_utc(row.updated_at),
    )


def _chunk(row: RetrievalChunkRow) -> RetrievalChunkRecord:
    return RetrievalChunkRecord(
        id=row.id,
        profile_id=row.profile_id,
        source_type=row.source_type,
        source_id=row.source_id,
        canonical_key=row.canonical_key,
        encrypted_content=row.encrypted_content,
        token_hashes=row.token_hashes_json,
        vector=row.vector_json,
        permitted_use=ClaimPermittedUse(row.permitted_use),
        evidence_claim_ids=row.evidence_claim_ids_json,
        provenance=row.provenance_json,
        created_at=_utc(row.created_at),
        updated_at=_utc(row.updated_at),
    )


class CandidateKnowledgeRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_import_bundle(
        self,
        document: CandidateDocument,
        version: CandidateDocumentVersionRecord,
        evidence: EvidenceSource,
        claims: list[CandidateClaim],
    ) -> None:
        try:
            self._session.add(
                DocumentRow(
                    id=document.id,
                    profile_id=document.profile_id,
                    kind=document.kind.value,
                    display_name=document.display_name,
                    variant_label=document.variant_label,
                    job_family_tags_json=document.job_family_tags,
                    is_primary=document.is_primary,
                    archived=document.archived,
                    created_at=document.created_at,
                )
            )
            self._session.add(
                DocumentVersionRow(
                    id=version.id,
                    document_id=version.document_id,
                    version=version.version,
                    file_name=version.file_name,
                    media_type=version.media_type,
                    sha256=version.sha256,
                    storage_path=version.storage_path,
                    encrypted_extraction=version.encrypted_extraction,
                    parser_version=version.parser_version,
                    page_count=version.page_count,
                    character_count=version.character_count,
                    created_at=version.created_at,
                )
            )
            self._session.add(
                EvidenceSourceRow(
                    id=evidence.id,
                    profile_id=evidence.profile_id,
                    document_version_id=evidence.document_version_id,
                    source_type=evidence.source_type,
                    source_label=evidence.source_label,
                    source_uri=evidence.source_uri,
                    content_hash=evidence.content_hash,
                    created_at=evidence.created_at,
                )
            )
            self._session.add_all(
                [
                    CandidateClaimRow(
                        id=claim.id,
                        profile_id=claim.profile_id,
                        evidence_source_id=claim.evidence_source_id,
                        canonical_key=claim.canonical_key,
                        statement=claim.statement,
                        claim_type=claim.claim_type.value,
                        value_json=claim.value,
                        source_location=claim.source_location,
                        context_json=claim.context,
                        start_date=claim.start_date,
                        end_date=claim.end_date,
                        confidence=claim.confidence,
                        verification_status=claim.verification_status.value,
                        permitted_use=claim.permitted_use.value,
                        sensitivity=claim.sensitivity.value,
                        locked=claim.locked,
                        superseded_by_id=claim.superseded_by_id,
                        created_at=claim.created_at,
                        updated_at=claim.updated_at,
                    )
                    for claim in claims
                ]
            )
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise

    def add_generated_bundle(
        self,
        document: CandidateDocument,
        version: CandidateDocumentVersionRecord,
        evidence: EvidenceSource,
        audit: DocumentGenerationAudit,
    ) -> None:
        try:
            self._session.add(
                DocumentRow(
                    id=document.id,
                    profile_id=document.profile_id,
                    kind=document.kind.value,
                    display_name=document.display_name,
                    variant_label=document.variant_label,
                    job_family_tags_json=document.job_family_tags,
                    is_primary=document.is_primary,
                    archived=document.archived,
                    created_at=document.created_at,
                )
            )
            self._session.add(
                DocumentVersionRow(
                    id=version.id,
                    document_id=version.document_id,
                    version=version.version,
                    file_name=version.file_name,
                    media_type=version.media_type,
                    sha256=version.sha256,
                    storage_path=version.storage_path,
                    encrypted_extraction=version.encrypted_extraction,
                    parser_version=version.parser_version,
                    page_count=version.page_count,
                    character_count=version.character_count,
                    created_at=version.created_at,
                )
            )
            self._session.add(
                EvidenceSourceRow(
                    id=evidence.id,
                    profile_id=evidence.profile_id,
                    document_version_id=evidence.document_version_id,
                    source_type=evidence.source_type,
                    source_label=evidence.source_label,
                    source_uri=evidence.source_uri,
                    content_hash=evidence.content_hash,
                    created_at=evidence.created_at,
                )
            )
            self._session.add(
                DocumentGenerationAuditRow(
                    id=audit.id,
                    application_id=audit.application_id,
                    profile_id=audit.profile_id,
                    job_id=audit.job_id,
                    document_version_id=audit.document_version_id,
                    kind=audit.kind.value,
                    output_format=audit.output_format.value,
                    review_fingerprint=audit.review_fingerprint,
                    evidence_claim_ids_json=audit.evidence_claim_ids,
                    requirement_ids_json=audit.requirement_ids,
                    missing_required_requirements_json=audit.missing_required_requirements,
                    created_at=audit.created_at,
                )
            )
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise

    def list_documents(self, profile_id: str) -> list[CandidateDocument]:
        statement = (
            select(DocumentRow)
            .where(DocumentRow.profile_id == profile_id)
            .order_by(DocumentRow.created_at.desc())
        )
        return [_document(row) for row in self._session.scalars(statement).all()]

    def get_document(self, document_id: str) -> CandidateDocument | None:
        row = self._session.get(DocumentRow, document_id)
        return _document(row) if row else None

    def list_versions(self, document_id: str) -> list[CandidateDocumentVersion]:
        statement = (
            select(DocumentVersionRow)
            .where(DocumentVersionRow.document_id == document_id)
            .order_by(DocumentVersionRow.version.desc())
        )
        return [
            CandidateDocumentVersion.model_validate(_version(row).model_dump())
            for row in self._session.scalars(statement).all()
        ]

    def get_version_record(self, version_id: str) -> CandidateDocumentVersionRecord | None:
        row = self._session.get(DocumentVersionRow, version_id)
        return _version(row) if row else None

    def list_claims(self, profile_id: str) -> list[CandidateClaim]:
        statement = (
            select(CandidateClaimRow)
            .where(CandidateClaimRow.profile_id == profile_id)
            .order_by(CandidateClaimRow.created_at, CandidateClaimRow.canonical_key)
        )
        return [_claim(row) for row in self._session.scalars(statement).all()]

    def get_claim(self, claim_id: str) -> CandidateClaim | None:
        row = self._session.get(CandidateClaimRow, claim_id)
        return _claim(row) if row else None

    def save_claim(self, claim: CandidateClaim) -> CandidateClaim:
        row = self._session.get(CandidateClaimRow, claim.id)
        if row is None:
            raise LookupError(f"Candidate claim {claim.id} was not found")
        row.statement = claim.statement
        row.value_json = claim.value
        row.confidence = claim.confidence
        row.verification_status = claim.verification_status.value
        row.permitted_use = claim.permitted_use.value
        row.sensitivity = claim.sensitivity.value
        row.locked = claim.locked
        row.superseded_by_id = claim.superseded_by_id
        row.updated_at = claim.updated_at
        self._session.commit()
        return _claim(row)

    def add_answer(self, answer: AnswerLibraryRecord) -> AnswerLibraryRecord:
        self._session.add(
            AnswerLibraryRow(
                id=answer.id,
                profile_id=answer.profile_id,
                canonical_field=answer.canonical_field,
                encrypted_question=answer.encrypted_question,
                encrypted_answer=answer.encrypted_answer,
                evidence_claim_ids_json=answer.evidence_claim_ids,
                confidence=answer.confidence,
                approved=answer.approved,
                locked=answer.locked,
                reuse_permission=answer.reuse_permission.value,
                provenance_json=answer.provenance,
                created_at=answer.created_at,
                updated_at=answer.updated_at,
            )
        )
        self._session.commit()
        return answer

    def list_answers(self, profile_id: str) -> list[AnswerLibraryRecord]:
        statement = (
            select(AnswerLibraryRow)
            .where(AnswerLibraryRow.profile_id == profile_id)
            .order_by(AnswerLibraryRow.updated_at.desc())
        )
        return [_answer(row) for row in self._session.scalars(statement).all()]

    def upsert_chunk(self, chunk: RetrievalChunkRecord) -> RetrievalChunkRecord:
        statement = select(RetrievalChunkRow).where(
            RetrievalChunkRow.source_type == chunk.source_type,
            RetrievalChunkRow.source_id == chunk.source_id,
        )
        row = self._session.scalar(statement)
        if row is None:
            row = RetrievalChunkRow(
                id=chunk.id,
                profile_id=chunk.profile_id,
                source_type=chunk.source_type,
                source_id=chunk.source_id,
                canonical_key=chunk.canonical_key,
                encrypted_content=chunk.encrypted_content,
                token_hashes_json=chunk.token_hashes,
                vector_json=chunk.vector,
                permitted_use=chunk.permitted_use.value,
                evidence_claim_ids_json=chunk.evidence_claim_ids,
                provenance_json=chunk.provenance,
                created_at=chunk.created_at,
                updated_at=chunk.updated_at,
            )
            self._session.add(row)
        else:
            row.canonical_key = chunk.canonical_key
            row.encrypted_content = chunk.encrypted_content
            row.token_hashes_json = chunk.token_hashes
            row.vector_json = chunk.vector
            row.permitted_use = chunk.permitted_use.value
            row.evidence_claim_ids_json = chunk.evidence_claim_ids
            row.provenance_json = chunk.provenance
            row.updated_at = chunk.updated_at
        self._session.commit()
        return _chunk(row)

    def delete_chunk(self, source_type: str, source_id: str) -> None:
        statement = select(RetrievalChunkRow).where(
            RetrievalChunkRow.source_type == source_type,
            RetrievalChunkRow.source_id == source_id,
        )
        row = self._session.scalar(statement)
        if row is not None:
            self._session.delete(row)
            self._session.commit()

    def list_chunks(self, profile_id: str) -> list[RetrievalChunkRecord]:
        statement = select(RetrievalChunkRow).where(RetrievalChunkRow.profile_id == profile_id)
        return [_chunk(row) for row in self._session.scalars(statement).all()]

    def add_generation_audit(self, audit: DocumentGenerationAudit) -> DocumentGenerationAudit:
        self._session.add(
            DocumentGenerationAuditRow(
                id=audit.id,
                application_id=audit.application_id,
                profile_id=audit.profile_id,
                job_id=audit.job_id,
                document_version_id=audit.document_version_id,
                kind=audit.kind.value,
                output_format=audit.output_format.value,
                review_fingerprint=audit.review_fingerprint,
                evidence_claim_ids_json=audit.evidence_claim_ids,
                requirement_ids_json=audit.requirement_ids,
                missing_required_requirements_json=audit.missing_required_requirements,
                created_at=audit.created_at,
            )
        )
        self._session.commit()
        return audit

    def list_generation_audits(self, application_id: str) -> list[DocumentGenerationAudit]:
        rows = self._session.scalars(
            select(DocumentGenerationAuditRow)
            .where(DocumentGenerationAuditRow.application_id == application_id)
            .order_by(DocumentGenerationAuditRow.created_at.desc())
        ).all()
        return [
            DocumentGenerationAudit(
                id=row.id,
                application_id=row.application_id,
                profile_id=row.profile_id,
                job_id=row.job_id,
                document_version_id=row.document_version_id,
                kind=DocumentKind(row.kind),
                output_format=DocumentOutputFormat(row.output_format),
                review_fingerprint=row.review_fingerprint,
                evidence_claim_ids=row.evidence_claim_ids_json,
                requirement_ids=row.requirement_ids_json,
                missing_required_requirements=row.missing_required_requirements_json,
                created_at=_utc(row.created_at),
            )
            for row in rows
        ]

    def add_submitted_document(
        self, evidence: SubmittedDocumentEvidence
    ) -> SubmittedDocumentEvidence:
        self._session.add(
            SubmittedDocumentEvidenceRow(
                id=evidence.id,
                application_id=evidence.application_id,
                document_version_id=evidence.document_version_id,
                role=evidence.role.value,
                file_name=evidence.file_name,
                sha256=evidence.sha256,
                upload_fingerprint=evidence.upload_fingerprint,
                captured_at=evidence.captured_at,
            )
        )
        self._session.commit()
        return evidence

    def list_submitted_documents(self, application_id: str) -> list[SubmittedDocumentEvidence]:
        rows = self._session.scalars(
            select(SubmittedDocumentEvidenceRow)
            .where(SubmittedDocumentEvidenceRow.application_id == application_id)
            .order_by(SubmittedDocumentEvidenceRow.captured_at)
        ).all()
        return [
            SubmittedDocumentEvidence(
                id=row.id,
                application_id=row.application_id,
                document_version_id=row.document_version_id,
                role=ApplicationDocumentRole(row.role),
                file_name=row.file_name,
                sha256=row.sha256,
                upload_fingerprint=row.upload_fingerprint,
                captured_at=_utc(row.captured_at),
            )
            for row in rows
        ]
