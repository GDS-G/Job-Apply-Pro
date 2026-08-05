from __future__ import annotations

import hashlib
import math
import re
from datetime import date
from pathlib import Path
from uuid import uuid4

from job_apply_pro.documents.claims import propose_claims
from job_apply_pro.documents.extractors import extract_document
from job_apply_pro.domain.candidate import CandidateBackup
from job_apply_pro.domain.knowledge import (
    AnswerLibraryCreate,
    AnswerLibraryEntry,
    AnswerLibraryRecord,
    CandidateClaim,
    CandidateDocument,
    CandidateDocumentVersion,
    CandidateDocumentVersionRecord,
    CandidateKnowledgeSnapshot,
    ClaimPermittedUse,
    ClaimReview,
    ClaimType,
    ClaimVerificationStatus,
    DocumentExtraction,
    DocumentImportResult,
    DocumentKind,
    EvidenceSource,
    ExperienceSummary,
    RetrievalChunkRecord,
    RetrievalQuery,
    RetrievalResult,
)
from job_apply_pro.domain.workflow import utc_now
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.storage.repository_contracts import (
    CandidateKnowledgeRepositoryProtocol,
    CandidateRepositoryProtocol,
)

TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9+#.-]{1,50}", re.IGNORECASE)
VECTOR_DIMENSIONS = 64


class CandidateKnowledgeError(RuntimeError):
    pass


class CandidateKnowledgeConflictError(CandidateKnowledgeError):
    pass


def _public_version(record: CandidateDocumentVersionRecord) -> CandidateDocumentVersion:
    return CandidateDocumentVersion.model_validate(record.model_dump())


def _month_index(value: date) -> int:
    return value.year * 12 + value.month - 1


class CandidateKnowledgeService:
    def __init__(
        self,
        repository: CandidateKnowledgeRepositoryProtocol,
        candidates: CandidateRepositoryProtocol,
        cipher: SensitiveDataCipher,
        *,
        document_data_dir: Path,
        document_max_bytes: int,
    ) -> None:
        self._repository = repository
        self._candidates = candidates
        self._cipher = cipher
        self._document_data_dir = document_data_dir.resolve()
        self._document_max_bytes = document_max_bytes

    def import_document(
        self,
        profile_id: str,
        *,
        file_name: str,
        data: bytes,
        kind: DocumentKind,
        display_name: str,
        variant_label: str,
        job_family_tags: list[str],
        is_primary: bool,
    ) -> DocumentImportResult:
        self._profile(profile_id)
        if not data:
            raise CandidateKnowledgeError("Imported document is empty")
        if len(data) > self._document_max_bytes:
            raise CandidateKnowledgeError(
                f"Imported document exceeds the {self._document_max_bytes}-byte limit"
            )
        safe_name = Path(file_name).name
        if not safe_name or safe_name != file_name:
            raise CandidateKnowledgeError("Document filename must not contain a path")
        media_type, extraction = extract_document(safe_name, data)
        now = utc_now()
        document_id = str(uuid4())
        version_id = str(uuid4())
        evidence_id = str(uuid4())
        sha256 = hashlib.sha256(data).hexdigest()
        document = CandidateDocument(
            id=document_id,
            profile_id=profile_id,
            kind=kind,
            display_name=display_name,
            variant_label=variant_label,
            job_family_tags=sorted(
                {" ".join(tag.strip().casefold().split()) for tag in job_family_tags if tag.strip()}
            ),
            is_primary=is_primary,
            archived=False,
            created_at=now,
        )
        destination = (self._document_data_dir / profile_id / document_id).resolve()
        if not destination.is_relative_to(self._document_data_dir):
            raise CandidateKnowledgeError("Document storage path escaped its approved root")
        destination.mkdir(parents=True, exist_ok=True)
        encrypted_file = self._cipher.encrypt_bytes(data, context=f"document:{version_id}:file")
        storage_path = destination / f"{version_id}.jap"
        temporary_path = destination / f"{version_id}.tmp"
        temporary_path.write_text(encrypted_file, encoding="ascii")
        temporary_path.replace(storage_path)
        version = CandidateDocumentVersionRecord(
            id=version_id,
            document_id=document_id,
            version=1,
            file_name=safe_name,
            media_type=media_type,
            sha256=sha256,
            parser_version=extraction.parser,
            page_count=extraction.page_count,
            character_count=extraction.character_count,
            created_at=now,
            storage_path=str(storage_path),
            encrypted_extraction=self._cipher.encrypt_json(
                extraction.model_dump(mode="json"),
                context=f"document:{version_id}:extraction",
            ),
        )
        evidence = EvidenceSource(
            id=evidence_id,
            profile_id=profile_id,
            document_version_id=version_id,
            source_type="IMPORTED_DOCUMENT",
            source_label=safe_name,
            source_uri=f"document-version:{version_id}",
            content_hash=sha256,
            created_at=now,
        )
        claims = propose_claims(profile_id, evidence_id, extraction)
        try:
            self._repository.add_import_bundle(document, version, evidence, claims)
        except Exception:
            storage_path.unlink(missing_ok=True)
            raise
        return DocumentImportResult(
            document=document,
            version=_public_version(version),
            extraction=extraction,
            proposed_claims=claims,
        )

    def list_documents(self, profile_id: str) -> list[CandidateDocument]:
        self._profile(profile_id)
        return self._repository.list_documents(profile_id)

    def list_versions(self, document_id: str) -> list[CandidateDocumentVersion]:
        if self._repository.get_document(document_id) is None:
            raise LookupError(f"Candidate document {document_id} was not found")
        return self._repository.list_versions(document_id)

    def get_extraction(self, version_id: str) -> DocumentExtraction:
        version = self._repository.get_version_record(version_id)
        if version is None:
            raise LookupError(f"Candidate document version {version_id} was not found")
        payload = self._cipher.decrypt_json(
            version.encrypted_extraction,
            context=f"document:{version.id}:extraction",
        )
        return DocumentExtraction.model_validate(payload)

    def list_claims(self, profile_id: str) -> list[CandidateClaim]:
        self._profile(profile_id)
        return self._repository.list_claims(profile_id)

    def review_claim(self, claim_id: str, review: ClaimReview) -> CandidateClaim:
        claim = self._repository.get_claim(claim_id)
        if claim is None:
            raise LookupError(f"Candidate claim {claim_id} was not found")
        if review.approved:
            conflicts = [
                item
                for item in self._repository.list_claims(claim.profile_id)
                if item.id != claim.id
                and item.canonical_key == claim.canonical_key
                and item.verification_status is ClaimVerificationStatus.VERIFIED
                and item.locked
                and item.superseded_by_id is None
            ]
            if conflicts:
                raise CandidateKnowledgeConflictError(
                    "A locked verified fact already exists for this canonical key"
                )
        now = utc_now()
        updated = claim.model_copy(
            update={
                "statement": review.statement or claim.statement,
                "value": review.value if review.value is not None else claim.value,
                "confidence": (
                    review.confidence if review.confidence is not None else claim.confidence
                ),
                "verification_status": (
                    ClaimVerificationStatus.VERIFIED
                    if review.approved
                    else ClaimVerificationStatus.REJECTED
                ),
                "permitted_use": review.permitted_use or claim.permitted_use,
                "sensitivity": review.sensitivity or claim.sensitivity,
                "locked": review.lock if review.approved else False,
                "updated_at": now,
            }
        )
        saved = self._repository.save_claim(updated)
        if saved.verification_status is ClaimVerificationStatus.VERIFIED and saved.locked:
            self._repository.upsert_chunk(
                self._chunk(
                    source_type="CLAIM",
                    source_id=saved.id,
                    profile_id=saved.profile_id,
                    canonical_key=saved.canonical_key,
                    content=saved.statement,
                    permitted_use=saved.permitted_use,
                    evidence_claim_ids=[saved.id],
                    provenance={
                        "evidence_source_id": saved.evidence_source_id,
                        "source_location": saved.source_location,
                        "verification": saved.verification_status.value,
                    },
                )
            )
        else:
            self._repository.delete_chunk("CLAIM", saved.id)
        return saved

    def calculate_experience(self, profile_id: str) -> list[ExperienceSummary]:
        claims = [
            claim
            for claim in self.list_claims(profile_id)
            if claim.claim_type is ClaimType.EXPERIENCE
            and claim.verification_status is ClaimVerificationStatus.VERIFIED
            and claim.locked
            and claim.start_date is not None
            and claim.end_date is not None
            and claim.superseded_by_id is None
        ]
        grouped: dict[str, list[tuple[int, int, str]]] = {}
        for claim in claims:
            if claim.start_date is None or claim.end_date is None:
                continue
            skill = str(claim.value.get("skill", "general"))
            grouped.setdefault(skill, []).append(
                (_month_index(claim.start_date), _month_index(claim.end_date), claim.id)
            )
        results: list[ExperienceSummary] = []
        for skill, periods in sorted(grouped.items()):
            merged: list[tuple[int, int]] = []
            supporting_ids: list[str] = []
            for start, end, claim_id in sorted(periods):
                supporting_ids.append(claim_id)
                if not merged or start > merged[-1][1] + 1:
                    merged.append((start, end))
                else:
                    prior_start, prior_end = merged[-1]
                    merged[-1] = (prior_start, max(prior_end, end))
            months = sum(end - start + 1 for start, end in merged)
            results.append(
                ExperienceSummary(
                    skill=skill,
                    months=months,
                    years=round(months / 12, 2),
                    supporting_claim_ids=supporting_ids,
                )
            )
        return results

    def add_answer(self, profile_id: str, command: AnswerLibraryCreate) -> AnswerLibraryEntry:
        self._profile(profile_id)
        claims = [self._repository.get_claim(claim_id) for claim_id in command.evidence_claim_ids]
        if any(
            claim is None
            or claim.profile_id != profile_id
            or claim.verification_status is not ClaimVerificationStatus.VERIFIED
            or not claim.locked
            for claim in claims
        ):
            raise CandidateKnowledgeConflictError(
                "Answer evidence must reference locked verified claims from this profile"
            )
        answer_id = str(uuid4())
        now = utc_now()
        record = AnswerLibraryRecord(
            id=answer_id,
            profile_id=profile_id,
            canonical_field=command.canonical_field,
            encrypted_question=self._cipher.encrypt_bytes(
                command.question.encode(), context=f"answer:{answer_id}:question"
            ),
            encrypted_answer=self._cipher.encrypt_bytes(
                command.answer.encode(), context=f"answer:{answer_id}:value"
            ),
            evidence_claim_ids=command.evidence_claim_ids,
            confidence=command.confidence,
            approved=command.approved,
            locked=command.locked,
            reuse_permission=command.reuse_permission,
            provenance={
                **command.provenance,
                "source": "USER_APPROVED_LIBRARY",
                "retrieval_policy": "locked-facts-only",
            },
            created_at=now,
            updated_at=now,
        )
        self._repository.add_answer(record)
        if record.approved and record.locked:
            self._repository.upsert_chunk(
                self._chunk(
                    source_type="ANSWER",
                    source_id=record.id,
                    profile_id=profile_id,
                    canonical_key=record.canonical_field,
                    content=f"{command.question}\n{command.answer}",
                    permitted_use=record.reuse_permission,
                    evidence_claim_ids=record.evidence_claim_ids,
                    provenance=record.provenance,
                )
            )
        return self._public_answer(record)

    def list_answers(self, profile_id: str) -> list[AnswerLibraryEntry]:
        self._profile(profile_id)
        return [self._public_answer(record) for record in self._repository.list_answers(profile_id)]

    def retrieve(self, profile_id: str, command: RetrievalQuery) -> list[RetrievalResult]:
        self._profile(profile_id)
        query_hashes, query_vector = self._features(command.query)
        allowed = {
            ClaimPermittedUse.ANY,
            command.permitted_use,
        }
        if command.permitted_use is ClaimPermittedUse.ANY:
            allowed = set(ClaimPermittedUse)
        scored: list[RetrievalResult] = []
        query_set = set(query_hashes)
        for chunk in self._repository.list_chunks(profile_id):
            if chunk.permitted_use not in allowed:
                continue
            chunk_set = set(chunk.token_hashes)
            union = query_set | chunk_set
            keyword_score = len(query_set & chunk_set) / len(union) if union else 0
            vector_score = max(0.0, self._cosine(query_vector, chunk.vector))
            score = min(1.0, 0.65 * keyword_score + 0.35 * vector_score)
            if score <= 0:
                continue
            content = self._cipher.decrypt_bytes(
                chunk.encrypted_content,
                context=f"retrieval:{chunk.id}",
            ).decode()
            scored.append(
                RetrievalResult(
                    source_type=chunk.source_type,
                    source_id=chunk.source_id,
                    canonical_key=chunk.canonical_key,
                    content=content,
                    score=round(score, 6),
                    evidence_claim_ids=chunk.evidence_claim_ids,
                    provenance=chunk.provenance,
                )
            )
        return sorted(scored, key=lambda item: (-item.score, item.canonical_key))[: command.limit]

    def snapshot(self, profile_id: str) -> CandidateKnowledgeSnapshot:
        return CandidateKnowledgeSnapshot(
            profile_id=profile_id,
            documents=self.list_documents(profile_id),
            claims=self.list_claims(profile_id),
            answers=self.list_answers(profile_id),
        )

    def _profile(self, profile_id: str) -> CandidateBackup:
        profile = self._candidates.get_encrypted(profile_id)
        if profile is None:
            raise LookupError(f"Candidate profile {profile_id} was not found")
        return profile

    def _public_answer(self, record: AnswerLibraryRecord) -> AnswerLibraryEntry:
        return AnswerLibraryEntry(
            id=record.id,
            profile_id=record.profile_id,
            question=self._cipher.decrypt_bytes(
                record.encrypted_question, context=f"answer:{record.id}:question"
            ).decode(),
            canonical_field=record.canonical_field,
            answer=self._cipher.decrypt_bytes(
                record.encrypted_answer, context=f"answer:{record.id}:value"
            ).decode(),
            evidence_claim_ids=record.evidence_claim_ids,
            confidence=record.confidence,
            approved=record.approved,
            locked=record.locked,
            reuse_permission=record.reuse_permission,
            provenance=record.provenance,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def _chunk(
        self,
        *,
        source_type: str,
        source_id: str,
        profile_id: str,
        canonical_key: str,
        content: str,
        permitted_use: ClaimPermittedUse,
        evidence_claim_ids: list[str],
        provenance: dict[str, object],
    ) -> RetrievalChunkRecord:
        chunk_id = f"chunk-{hashlib.sha256(f'{source_type}:{source_id}'.encode()).hexdigest()[:30]}"
        token_hashes, vector = self._features(content)
        now = utc_now()
        return RetrievalChunkRecord(
            id=chunk_id,
            profile_id=profile_id,
            source_type=source_type,
            source_id=source_id,
            canonical_key=canonical_key,
            encrypted_content=self._cipher.encrypt_bytes(
                content.encode(), context=f"retrieval:{chunk_id}"
            ),
            token_hashes=token_hashes,
            vector=vector,
            permitted_use=permitted_use,
            evidence_claim_ids=evidence_claim_ids,
            provenance={**provenance, "embedding": "keyed-hashing-v1"},
            created_at=now,
            updated_at=now,
        )

    def _features(self, text: str) -> tuple[list[str], list[float]]:
        tokens = sorted(set(TOKEN_PATTERN.findall(text.casefold())))
        hashes = [self._cipher.blind_index(token, context="retrieval-token") for token in tokens]
        vector = [0.0] * VECTOR_DIMENSIONS
        for token_hash in hashes:
            bucket = int(token_hash[:8], 16) % VECTOR_DIMENSIONS
            sign = 1.0 if int(token_hash[8:10], 16) % 2 == 0 else -1.0
            vector[bucket] += sign
        magnitude = math.sqrt(sum(value * value for value in vector))
        if magnitude:
            vector = [value / magnitude for value in vector]
        return hashes, vector

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        if len(left) != len(right):
            return 0
        return sum(a * b for a, b in zip(left, right, strict=True))
