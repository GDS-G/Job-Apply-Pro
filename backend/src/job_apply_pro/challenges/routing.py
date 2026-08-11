from __future__ import annotations

from typing import ClassVar

from job_apply_pro.domain.ai import AICapability
from job_apply_pro.domain.challenges import (
    ChallengeModelRoute,
    ChallengeModelTier,
    ChallengeQuestion,
    QuestionKind,
)


class ChallengeModelRoutingPolicy:
    """Provider-independent routing hints consumed by the existing AI gateway."""

    _reasoning_kinds: ClassVar[set[QuestionKind]] = {
        QuestionKind.LONG_TEXT,
        QuestionKind.MATCHING,
        QuestionKind.ORDERING,
    }

    def route(
        self,
        question: ChallengeQuestion,
        *,
        instruction_length: int,
        prior_confidence: float | None = None,
    ) -> ChallengeModelRoute:
        if question.kind is QuestionKind.VISUAL:
            return self._decision(
                question, ChallengeModelTier.MULTIMODAL, {AICapability.MULTIMODAL}, False
            )
        if instruction_length > 6_000:
            return self._decision(
                question,
                ChallengeModelTier.LONG_CONTEXT,
                {AICapability.TEXT, AICapability.STRUCTURED_OUTPUT},
                True,
            )
        if prior_confidence is not None and prior_confidence < 0.65:
            return self._decision(
                question,
                ChallengeModelTier.STRONG_REASONING,
                {AICapability.TEXT, AICapability.STRUCTURED_OUTPUT},
                False,
                "Prior answer confidence was below 0.65",
            )
        technical = any(
            token in question.prompt.casefold()
            for token in ("code", "algorithm", "architecture", "scenario", "debug")
        )
        if question.kind in self._reasoning_kinds or technical:
            return self._decision(
                question,
                ChallengeModelTier.STRONG_REASONING,
                {AICapability.TEXT, AICapability.STRUCTURED_OUTPUT},
                True,
            )
        return self._decision(question, ChallengeModelTier.FAST_TEXT, {AICapability.TEXT}, True)

    @staticmethod
    def _decision(
        question: ChallengeQuestion,
        tier: ChallengeModelTier,
        capabilities: set[AICapability],
        cache_allowed: bool,
        escalation_reason: str | None = None,
    ) -> ChallengeModelRoute:
        return ChallengeModelRoute(
            question_id=question.id,
            tier=tier,
            required_capabilities=capabilities,
            cache_allowed=cache_allowed,
            escalation_reason=escalation_reason,
        )
