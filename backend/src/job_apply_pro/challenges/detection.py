from __future__ import annotations

import re
from uuid import uuid4

from job_apply_pro.domain.browser import BrowserObservation
from job_apply_pro.domain.challenges import (
    CaptchaType,
    ChallengeDetection,
    ChallengeKind,
    ChallengeQuestion,
    QuestionKind,
)
from job_apply_pro.domain.workflow import utc_now


class ChallengeDetectionError(ValueError):
    pass


_CAPTCHA_PROVIDERS = {
    "recaptcha": "reCAPTCHA",
    "hcaptcha": "hCaptcha",
    "turnstile": "Cloudflare Turnstile",
    "arkose": "Arkose Labs",
    "funcaptcha": "Arkose Labs",
}


class ChallengeDetector:
    def detect(self, observation: BrowserObservation) -> ChallengeDetection:
        haystack = " ".join(
            [observation.page_type, observation.visible_text]
            + [
                " ".join(
                    (
                        control.input_type,
                        control.role,
                        control.group_label,
                        control.label,
                        control.text,
                    )
                )
                for control in observation.controls
            ]
        ).casefold()
        signatures = [key for key in _CAPTCHA_PROVIDERS if key in haystack]
        if "captcha" in haystack or signatures:
            provider = _CAPTCHA_PROVIDERS.get(signatures[0]) if signatures else None
            captcha_type = CaptchaType.INTERACTIVE
            if "audio" in haystack:
                captcha_type = CaptchaType.AUDIO
            elif "image" in haystack:
                captcha_type = CaptchaType.IMAGE
            return ChallengeDetection(
                kind=ChallengeKind.CAPTCHA,
                page_type=observation.page_type,
                provider=provider,
                captcha_type=captcha_type,
                signatures=signatures or ["captcha"],
                page_fingerprint=observation.page_fingerprint,
                detected_at=utc_now(),
            )
        page_type = observation.page_type.upper()
        if "ASSESSMENT" in page_type:
            kind = ChallengeKind.ASSESSMENT
        elif "QUIZ" in page_type:
            kind = ChallengeKind.QUIZ
        elif "QUESTIONNAIRE" in page_type or "SCREENING" in page_type:
            kind = ChallengeKind.QUESTIONNAIRE
        else:
            raise ChallengeDetectionError("No supported challenge was detected")
        return ChallengeDetection(
            kind=kind,
            page_type=observation.page_type,
            signatures=[page_type],
            page_fingerprint=observation.page_fingerprint,
            detected_at=utc_now(),
        )

    def questions(self, observation: BrowserObservation) -> list[ChallengeQuestion]:
        questions: list[ChallengeQuestion] = []
        seen_radio_groups: set[str] = set()
        for control in observation.controls:
            tag = control.tag
            input_type = control.input_type
            if tag not in {"input", "select", "textarea"} or input_type in {
                "hidden",
                "submit",
                "button",
                "file",
            }:
                continue
            prompt = (control.label or control.field_name).strip()
            if not prompt:
                continue
            if input_type == "radio":
                group = control.field_name or prompt
                if group in seen_radio_groups:
                    continue
                seen_radio_groups.add(group)
                members = [
                    item
                    for item in observation.controls
                    if item.input_type == "radio" and item.field_name == group
                ]
                group_prompt = (control.group_label or group).strip()
                questions.append(
                    ChallengeQuestion(
                        id=group,
                        position=len(questions) + 1,
                        prompt=group_prompt,
                        kind=QuestionKind.MULTIPLE_CHOICE,
                        options=[item.label or item.field_name for item in members],
                        required=any(item.required for item in members),
                        canonical_field=control.canonical_field or None,
                    )
                )
                continue
            if tag == "textarea":
                kind = QuestionKind.LONG_TEXT
            elif tag == "select":
                kind = QuestionKind.SELECT
            elif input_type == "checkbox":
                kind = QuestionKind.CHECKBOX
            else:
                kind = QuestionKind.TEXT
            options = [option.label or option.value for option in control.options]
            lowered = prompt.casefold()
            questions.append(
                ChallengeQuestion(
                    id=control.element_id or control.field_name or str(uuid4()),
                    position=len(questions) + 1,
                    prompt=prompt,
                    kind=kind,
                    options=options,
                    required=control.required,
                    character_limit=control.character_limit,
                    canonical_field=control.canonical_field or None,
                    legal_attestation=control.legal_attestation
                    or bool(re.search(r"\b(attest|certify|acknowledge|under penalty)\b", lowered)),
                    signature_required="signature" in lowered,
                )
            )
        return questions

    def visible_timer_seconds(self, observation: BrowserObservation) -> int | None:
        match = re.search(r"\b(\d{1,2}):(\d{2})\b", observation.visible_text)
        return int(match.group(1)) * 60 + int(match.group(2)) if match else None
