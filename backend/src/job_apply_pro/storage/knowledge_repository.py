from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from job_apply_pro.domain.applications import (
    ApplicationAnswerRecord,
    ApplicationAnswerSource,
    ApplicationAnswerStatus,
    ApplicationDocumentRole,
    SubmittedDocumentEvidence,
)
from job_apply_pro.domain.knowledge import (
    AnswerLibraryRecord,
    AnswerLibraryRevisionRecord,
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
    DocumentSelectionAudit,
    DocumentTemplate,
    EvidenceSource,
    RetrievalChunkRecord,
    SensitivityLevel,
    TailoringRankingMode,
)
from job_apply_pro.storage.models import (
    AnswerLibraryRevisionRow,
    AnswerLibraryRow,
    ApplicationAnswerRow,
    ApplicationRow,
    CandidateClaimRow,
    DocumentGenerationAuditRow,
    DocumentRow,
    DocumentSelectionAuditRow,
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
        revision=row.revision,
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


def _answer_revision(row: AnswerLibraryRevisionRow) -> AnswerLibraryRevisionRecord:
    return AnswerLibraryRevisionRecord(
        id=row.id,
        answer_id=row.answer_id,
        profile_id=row.profile_id,
        revision=row.revision,
        encrypted_question=row.encrypted_question,
        canonical_field=row.canonical_field,
        encrypted_answer=row.encrypted_answer,
        evidence_claim_ids=row.evidence_claim_ids_json,
        confidence=row.confidence,
        approved=row.approved,
        locked=row.locked,
        reuse_permission=ClaimPermittedUse(row.reuse_permission),
        provenance=row.provenance_json,
        created_at=_utc(row.created_at),
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


def _application_answer(row: ApplicationAnswerRow) -> ApplicationAnswerRecord:
    return ApplicationAnswerRecord(
        id=row.id,
        application_id=row.application_id,
        profile_id=row.profile_id or "",
        job_id=row.job_id or "",
        revision=row.revision,
        encrypted_question=row.encrypted_question,
        encrypted_normalized_question=row.encrypted_normalized_question,
        canonical_field=row.canonical_field,
        encrypted_value=row.encrypted_value,
        status=ApplicationAnswerStatus(row.status),
        source_type=ApplicationAnswerSource(row.source_type),
        source_answer_id=row.source_answer_id,
        library_answer_id=row.library_answer_id,
        evidence_claim_ids=row.evidence_claim_ids_json,
        retrieval_results=row.retrieval_results_json,
        provider_id=row.provider_id,
        model_id=row.model_id,
        prompt_version=row.prompt_version,
        policy_version=row.policy_version,
        confidence=row.confidence,
        encrypted_generated_value=row.encrypted_generated_value,
        character_limit=row.character_limit,
        character_limit_applied=row.character_limit_applied,
        limitations=row.limitations_json,
        user_edited=row.user_edited,
        reuse_permission=row.reuse_permission,
        created_at=_utc(row.created_at),
        updated_at=_utc(row.updated_at or row.created_at),
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
            if document.is_primary:
                self._session.execute(
                    update(DocumentRow)
                    .where(
                        DocumentRow.profile_id == document.profile_id,
                        DocumentRow.kind == document.kind.value,
                        DocumentRow.is_primary.is_(True),
                    )
                    .values(is_primary=False)
                )
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
                    template=audit.template.value,
                    ranking_mode=audit.ranking_mode.value,
                    ranking_method=audit.ranking_method,
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

    def add_answer(
        self,
        answer: AnswerLibraryRecord,
        retrieval_chunk: RetrievalChunkRecord | None,
    ) -> AnswerLibraryRecord:
        try:
            self._session.add(
                AnswerLibraryRow(
                    id=answer.id,
                    revision=answer.revision,
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
            self._session.add(self._answer_revision_row(answer))
            self._replace_answer_chunk(answer.id, retrieval_chunk)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return answer

    def add_application_answer(self, answer: ApplicationAnswerRecord) -> ApplicationAnswerRecord:
        try:
            self._session.add(self._application_answer_row(answer))
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return answer

    def get_application_answer(self, answer_id: str) -> ApplicationAnswerRecord | None:
        row = self._session.get(ApplicationAnswerRow, answer_id)
        return _application_answer(row) if row is not None else None

    def list_application_answers(self, application_id: str) -> list[ApplicationAnswerRecord]:
        rows = self._session.scalars(
            select(ApplicationAnswerRow)
            .where(ApplicationAnswerRow.application_id == application_id)
            .order_by(
                ApplicationAnswerRow.updated_at.desc(), ApplicationAnswerRow.created_at.desc()
            )
        ).all()
        return [_application_answer(row) for row in rows]

    def update_application_answer(
        self, answer: ApplicationAnswerRecord, expected_revision: int
    ) -> ApplicationAnswerRecord:
        row = self._session.get(ApplicationAnswerRow, answer.id)
        if row is None:
            raise LookupError(f"Application answer {answer.id} was not found")
        try:
            result: CursorResult[object] = self._session.connection().execute(
                update(ApplicationAnswerRow)
                .where(
                    ApplicationAnswerRow.id == answer.id,
                    ApplicationAnswerRow.revision == expected_revision,
                )
                .values(**self._application_answer_values(answer))
            )
            if result.rowcount != 1:
                raise ValueError("Application answer revision is stale")
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return answer

    def promote_application_answer(
        self,
        application_answer: ApplicationAnswerRecord,
        expected_revision: int,
        library_answer: AnswerLibraryRecord,
        retrieval_chunk: RetrievalChunkRecord,
    ) -> ApplicationAnswerRecord:
        try:
            result: CursorResult[object] = self._session.connection().execute(
                update(ApplicationAnswerRow)
                .where(
                    ApplicationAnswerRow.id == application_answer.id,
                    ApplicationAnswerRow.revision == expected_revision,
                )
                .values(**self._application_answer_values(application_answer))
            )
            if result.rowcount != 1:
                raise ValueError("Application answer revision is stale")
            self._session.add(self._answer_row(library_answer))
            self._session.add(self._answer_revision_row(library_answer))
            self._replace_answer_chunk(library_answer.id, retrieval_chunk)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return application_answer

    def get_answer(self, answer_id: str) -> AnswerLibraryRecord | None:
        row = self._session.get(AnswerLibraryRow, answer_id)
        return _answer(row) if row is not None else None

    def update_answer(
        self,
        answer: AnswerLibraryRecord,
        expected_revision: int,
        retrieval_chunk: RetrievalChunkRecord | None,
    ) -> AnswerLibraryRecord:
        row = self._session.get(AnswerLibraryRow, answer.id)
        if row is None:
            raise LookupError(f"Answer library entry {answer.id} was not found")
        if row.revision != expected_revision or answer.revision != expected_revision + 1:
            raise ValueError("Answer library revision is stale")
        try:
            result: CursorResult[object] = self._session.connection().execute(
                update(AnswerLibraryRow)
                .where(
                    AnswerLibraryRow.id == answer.id,
                    AnswerLibraryRow.revision == expected_revision,
                )
                .values(
                    revision=answer.revision,
                    canonical_field=answer.canonical_field,
                    encrypted_question=answer.encrypted_question,
                    encrypted_answer=answer.encrypted_answer,
                    evidence_claim_ids_json=answer.evidence_claim_ids,
                    confidence=answer.confidence,
                    approved=answer.approved,
                    locked=answer.locked,
                    reuse_permission=answer.reuse_permission.value,
                    provenance_json=answer.provenance,
                    updated_at=answer.updated_at,
                )
            )
            if result.rowcount != 1:
                raise ValueError("Answer library revision is stale")
            self._session.add(self._answer_revision_row(answer))
            self._replace_answer_chunk(answer.id, retrieval_chunk)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return answer

    def list_answer_revisions(self, answer_id: str) -> list[AnswerLibraryRevisionRecord]:
        statement = (
            select(AnswerLibraryRevisionRow)
            .where(AnswerLibraryRevisionRow.answer_id == answer_id)
            .order_by(AnswerLibraryRevisionRow.revision.desc())
        )
        return [_answer_revision(row) for row in self._session.scalars(statement).all()]

    @staticmethod
    def _answer_revision_row(answer: AnswerLibraryRecord) -> AnswerLibraryRevisionRow:
        return AnswerLibraryRevisionRow(
            id=str(uuid4()),
            answer_id=answer.id,
            profile_id=answer.profile_id,
            revision=answer.revision,
            encrypted_question=answer.encrypted_question,
            canonical_field=answer.canonical_field,
            encrypted_answer=answer.encrypted_answer,
            evidence_claim_ids_json=answer.evidence_claim_ids,
            confidence=answer.confidence,
            approved=answer.approved,
            locked=answer.locked,
            reuse_permission=answer.reuse_permission.value,
            provenance_json=answer.provenance,
            created_at=answer.updated_at,
        )

    @staticmethod
    def _answer_row(answer: AnswerLibraryRecord) -> AnswerLibraryRow:
        return AnswerLibraryRow(
            id=answer.id,
            revision=answer.revision,
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

    @staticmethod
    def _application_answer_row(answer: ApplicationAnswerRecord) -> ApplicationAnswerRow:
        return ApplicationAnswerRow(
            id=answer.id,
            application_id=answer.application_id,
            created_at=answer.created_at,
            **CandidateKnowledgeRepository._application_answer_values(answer),
        )

    @staticmethod
    def _application_answer_values(answer: ApplicationAnswerRecord) -> dict[str, object]:
        return {
            "profile_id": answer.profile_id,
            "job_id": answer.job_id,
            "revision": answer.revision,
            "encrypted_question": answer.encrypted_question,
            "encrypted_normalized_question": answer.encrypted_normalized_question,
            "canonical_field": answer.canonical_field,
            "encrypted_value": answer.encrypted_value,
            "provenance": answer.source_type.value,
            "status": answer.status.value,
            "source_type": answer.source_type.value,
            "source_answer_id": answer.source_answer_id,
            "library_answer_id": answer.library_answer_id,
            "evidence_claim_ids_json": answer.evidence_claim_ids,
            "retrieval_results_json": answer.retrieval_results,
            "provider_id": answer.provider_id,
            "model_id": answer.model_id,
            "prompt_version": answer.prompt_version,
            "policy_version": answer.policy_version,
            "confidence": answer.confidence,
            "encrypted_generated_value": answer.encrypted_generated_value,
            "character_limit": answer.character_limit,
            "character_limit_applied": answer.character_limit_applied,
            "limitations_json": answer.limitations,
            "user_edited": answer.user_edited,
            "reuse_permission": answer.reuse_permission,
            "approved": answer.status
            in {
                ApplicationAnswerStatus.REVIEWED,
                ApplicationAnswerStatus.PROMOTED,
            },
            "updated_at": answer.updated_at,
        }

    def list_answers(self, profile_id: str) -> list[AnswerLibraryRecord]:
        statement = (
            select(AnswerLibraryRow)
            .where(AnswerLibraryRow.profile_id == profile_id)
            .order_by(AnswerLibraryRow.updated_at.desc())
        )
        return [_answer(row) for row in self._session.scalars(statement).all()]

    def upsert_chunk(self, chunk: RetrievalChunkRecord) -> RetrievalChunkRecord:
        row = self._upsert_chunk_row(chunk)
        self._session.commit()
        return _chunk(row)

    def _upsert_chunk_row(self, chunk: RetrievalChunkRecord) -> RetrievalChunkRow:
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
        return row

    def _replace_answer_chunk(
        self, answer_id: str, retrieval_chunk: RetrievalChunkRecord | None
    ) -> None:
        statement = select(RetrievalChunkRow).where(
            RetrievalChunkRow.source_type == "ANSWER",
            RetrievalChunkRow.source_id == answer_id,
        )
        existing = self._session.scalar(statement)
        if retrieval_chunk is None:
            if existing is not None:
                self._session.delete(existing)
            return
        self._upsert_chunk_row(retrieval_chunk)

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
                template=audit.template.value,
                ranking_mode=audit.ranking_mode.value,
                ranking_method=audit.ranking_method,
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
                template=DocumentTemplate(row.template),
                ranking_mode=TailoringRankingMode(row.ranking_mode),
                ranking_method=row.ranking_method,
                review_fingerprint=row.review_fingerprint,
                evidence_claim_ids=row.evidence_claim_ids_json,
                requirement_ids=row.requirement_ids_json,
                missing_required_requirements=row.missing_required_requirements_json,
                created_at=_utc(row.created_at),
            )
            for row in rows
        ]

    def approve_selection(self, audit: DocumentSelectionAudit) -> DocumentSelectionAudit:
        application = self._session.get(ApplicationRow, audit.application_id)
        if application is None:
            raise LookupError(f"Application {audit.application_id} was not found")
        try:
            application.selected_document_version_id = audit.document_version_id
            application.updated_at = audit.created_at
            self._session.add(
                DocumentSelectionAuditRow(
                    id=audit.id,
                    application_id=audit.application_id,
                    profile_id=audit.profile_id,
                    job_id=audit.job_id,
                    document_id=audit.document_id,
                    document_version_id=audit.document_version_id,
                    score=audit.score,
                    review_fingerprint=audit.review_fingerprint,
                    criteria_json=audit.criteria,
                    reasons_json=audit.reasons,
                    created_at=audit.created_at,
                )
            )
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return audit

    def list_selection_audits(self, application_id: str) -> list[DocumentSelectionAudit]:
        rows = self._session.scalars(
            select(DocumentSelectionAuditRow)
            .where(DocumentSelectionAuditRow.application_id == application_id)
            .order_by(DocumentSelectionAuditRow.created_at.desc())
        ).all()
        return [
            DocumentSelectionAudit(
                id=row.id,
                application_id=row.application_id,
                profile_id=row.profile_id,
                job_id=row.job_id,
                document_id=row.document_id,
                document_version_id=row.document_version_id,
                score=row.score,
                review_fingerprint=row.review_fingerprint,
                criteria=row.criteria_json,
                reasons=row.reasons_json,
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
