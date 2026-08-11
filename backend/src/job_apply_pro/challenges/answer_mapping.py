from __future__ import annotations

import re

from job_apply_pro.domain.candidate import ContactDetails
from job_apply_pro.domain.challenges import (
    AnswerSource,
    ChallengeAnswerSuggestion,
    ChallengeQuestion,
    ChallengeSessionSnapshot,
)
from job_apply_pro.domain.knowledge import ClaimPermittedUse
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.storage.repository_contracts import (
    CandidateKnowledgeRepositoryProtocol,
    CandidateRepositoryProtocol,
)


class ChallengeAnswerMapper:
    """Suggest only encrypted profile facts or approved, reusable answer-library values."""

    def __init__(
        self,
        candidates: CandidateRepositoryProtocol,
        knowledge: CandidateKnowledgeRepositoryProtocol,
        cipher: SensitiveDataCipher,
    ) -> None:
        self._candidates = candidates
        self._knowledge = knowledge
        self._cipher = cipher

    def suggest(
        self, snapshot: ChallengeSessionSnapshot, profile_id: str
    ) -> list[ChallengeAnswerSuggestion]:
        backup = self._candidates.get_encrypted(profile_id)
        if backup is None:
            raise LookupError(f"Candidate profile {profile_id} was not found")
        contact = ContactDetails.model_validate(
            self._cipher.decrypt_json(
                backup.encrypted_contact, context=f"candidate:{profile_id}:contact"
            )
        )
        contact_values = {
            "full_name": contact.full_name,
            "name": contact.full_name,
            "email": contact.email,
            "phone": contact.phone,
            "address": contact.address,
        }
        library = [
            item
            for item in self._knowledge.list_answers(profile_id)
            if item.approved
            and item.locked
            and item.reuse_permission in {ClaimPermittedUse.APPLICATIONS, ClaimPermittedUse.ANY}
        ]
        suggestions: list[ChallengeAnswerSuggestion] = []
        for question in snapshot.questions:
            if question.legal_attestation or question.signature_required:
                continue
            canonical = self._canonical(question)
            value = contact_values.get(canonical)
            if value:
                suggestions.append(
                    ChallengeAnswerSuggestion(
                        question_id=question.id,
                        value=value,
                        source=AnswerSource.CANDIDATE_PROFILE,
                        provenance={"canonical_field": canonical, "profile_id": profile_id},
                        confidence=1,
                    )
                )
                continue
            match = next(
                (
                    item
                    for item in library
                    if self._normalize(item.canonical_field) == canonical
                    or self._normalize(item.canonical_field)
                    == self._normalize(question.canonical_field or "")
                ),
                None,
            )
            if match is None:
                continue
            suggestions.append(
                ChallengeAnswerSuggestion(
                    question_id=question.id,
                    value=self._cipher.decrypt_bytes(
                        match.encrypted_answer,
                        context=f"answer:{match.id}:value",
                    ).decode(),
                    source=AnswerSource.ANSWER_LIBRARY,
                    provenance={
                        "answer_id": match.id,
                        "evidence_claim_ids": match.evidence_claim_ids,
                        "reuse_permission": match.reuse_permission.value,
                    },
                    confidence=match.confidence,
                )
            )
        return suggestions

    @classmethod
    def _canonical(cls, question: ChallengeQuestion) -> str:
        explicit = cls._normalize(question.canonical_field or "")
        if explicit:
            return explicit
        prompt = cls._normalize(question.prompt)
        for field, signatures in {
            "full_name": ("full name", "legal name", "your name"),
            "email": ("email", "e mail"),
            "phone": ("phone", "mobile", "telephone"),
            "address": ("address", "street"),
        }.items():
            if any(signature in prompt for signature in signatures):
                return field
        return prompt

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
