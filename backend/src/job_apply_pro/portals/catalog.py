from __future__ import annotations

from urllib.parse import urlsplit

from job_apply_pro.domain.portals import (
    PortalAdapterDefinition,
    PortalCapability,
    PortalConfirmationRule,
    PortalExecutionStrategy,
    PortalFingerprintRule,
    PortalKind,
    PortalPageMatch,
    PortalRegressionMetric,
    PortalReplayCase,
    PortalSupportStatus,
)


class PortalCatalogError(ValueError):
    pass


_FLOW_CAPABILITIES = [
    PortalCapability.SEARCH,
    PortalCapability.JOB_EXTRACTION,
    PortalCapability.APPLICATION_LAUNCH,
    PortalCapability.LOGIN,
    PortalCapability.MFA,
    PortalCapability.CAPTCHA,
    PortalCapability.MULTI_PAGE_FORM,
    PortalCapability.DOCUMENT_UPLOAD,
    PortalCapability.QUESTIONNAIRE,
    PortalCapability.ASSESSMENT,
    PortalCapability.SUBMISSION,
    PortalCapability.CONFIRMATION,
]

_REQUIRED_REPLAY_PAGE_TYPES = {
    "APPLICATION_FORM",
    "CONFIRMATION",
    "JOB_DETAIL",
    "JOB_SEARCH_RESULTS",
}


def _definition(
    kind: PortalKind,
    name: str,
    domains: list[str],
    brand: str,
    *,
    board: bool = False,
) -> PortalAdapterDefinition:
    capabilities = [*_FLOW_CAPABILITIES]
    if board:
        capabilities.insert(2, PortalCapability.SAVED_JOBS)
    return PortalAdapterDefinition(
        kind=kind,
        display_name=name,
        domains=domains,
        strategy=PortalExecutionStrategy.GENERIC_AGENT,
        capabilities=capabilities,
        fingerprints=[
            PortalFingerprintRule(
                page_type="JOB_SEARCH_RESULTS",
                required_signals=[brand, "jobs"],
                capability=PortalCapability.SEARCH,
            ),
            PortalFingerprintRule(
                page_type="JOB_DETAIL",
                required_signals=[brand, "apply"],
                capability=PortalCapability.JOB_EXTRACTION,
            ),
            PortalFingerprintRule(
                page_type="LOGIN",
                required_signals=[brand, "sign in"],
                capability=PortalCapability.LOGIN,
            ),
            PortalFingerprintRule(
                page_type="MFA",
                required_signals=[brand, "verification code"],
                capability=PortalCapability.MFA,
            ),
            PortalFingerprintRule(
                page_type="CAPTCHA",
                required_signals=[brand, "security check"],
                capability=PortalCapability.CAPTCHA,
            ),
            PortalFingerprintRule(
                page_type="APPLICATION_FORM",
                required_signals=[brand, "submit"],
                capability=PortalCapability.MULTI_PAGE_FORM,
            ),
            PortalFingerprintRule(
                page_type="DOCUMENT_UPLOAD",
                required_signals=[brand, "upload resume"],
                capability=PortalCapability.DOCUMENT_UPLOAD,
            ),
            PortalFingerprintRule(
                page_type="QUESTIONNAIRE",
                required_signals=[brand, "application questions"],
                capability=PortalCapability.QUESTIONNAIRE,
            ),
            PortalFingerprintRule(
                page_type="ASSESSMENT",
                required_signals=[brand, "assessment"],
                capability=PortalCapability.ASSESSMENT,
            ),
            PortalFingerprintRule(
                page_type="SUBMISSION_REVIEW",
                required_signals=[brand, "review application"],
                capability=PortalCapability.SUBMISSION,
            ),
            PortalFingerprintRule(
                page_type="CONFIRMATION",
                required_signals=[brand, "application received"],
                capability=PortalCapability.CONFIRMATION,
            ),
        ],
        confirmation=PortalConfirmationRule(
            page_types=["CONFIRMATION", "APPLICATION_COMPLETE"],
            required_text_patterns=["application submitted", "application received"],
            require_identifier=True,
        ),
        support_status=PortalSupportStatus.REPLAY_VALIDATED,
        production_enabled=False,
        replay_validated_page_types=sorted(_REQUIRED_REPLAY_PAGE_TYPES),
        live_validated_page_types=[],
        limitations=[
            "Production execution is disabled",
            "Live fingerprints require supervised validation before enablement",
            "Login, MFA, CAPTCHA, legal fields, and final submission require intervention policy",
        ],
        adapter_version="0.9.0",
    )


PORTAL_DEFINITIONS = (
    _definition(
        PortalKind.LINKEDIN,
        "LinkedIn",
        ["linkedin.com", "www.linkedin.com"],
        "linkedin",
        board=True,
    ),
    _definition(
        PortalKind.INDEED, "Indeed", ["indeed.com", "www.indeed.com"], "indeed", board=True
    ),
    _definition(
        PortalKind.MONSTER, "Monster", ["monster.com", "www.monster.com"], "monster", board=True
    ),
    _definition(
        PortalKind.CAREERBUILDER,
        "CareerBuilder",
        ["careerbuilder.com", "www.careerbuilder.com"],
        "careerbuilder",
        board=True,
    ),
    _definition(PortalKind.DICE, "Dice", ["dice.com", "www.dice.com"], "dice", board=True),
    _definition(
        PortalKind.ZIPRECRUITER,
        "ZipRecruiter",
        ["ziprecruiter.com", "www.ziprecruiter.com"],
        "ziprecruiter",
        board=True,
    ),
    _definition(
        PortalKind.GLASSDOOR,
        "Glassdoor",
        ["glassdoor.com", "www.glassdoor.com"],
        "glassdoor",
        board=True,
    ),
    _definition(
        PortalKind.WORKDAY,
        "Workday",
        ["myworkdayjobs.com", "workday.com"],
        "workday",
    ),
    _definition(PortalKind.TALEO, "Taleo", ["taleo.net"], "taleo"),
    _definition(
        PortalKind.GREENHOUSE,
        "Greenhouse",
        ["greenhouse.io", "boards.greenhouse.io"],
        "greenhouse",
    ),
    _definition(
        PortalKind.COMPANY_CAREERS,
        "Company careers site",
        ["*"],
        "careers",
    ),
)


class PortalCatalog:
    def __init__(
        self, definitions: tuple[PortalAdapterDefinition, ...] = PORTAL_DEFINITIONS
    ) -> None:
        self._definitions = definitions

    def definitions(self) -> list[PortalAdapterDefinition]:
        return list(self._definitions)

    def get(self, kind: PortalKind) -> PortalAdapterDefinition:
        for definition in self._definitions:
            if definition.kind is kind:
                return definition
        raise LookupError(f"Portal adapter {kind} was not found")

    def identify(
        self,
        *,
        url: str,
        page_type: str | None,
        visible_text: str,
        control_labels: list[str],
        page_fingerprint: str,
    ) -> PortalPageMatch:
        hostname = (urlsplit(url).hostname or "").casefold()
        definition = next(
            (
                item
                for item in self._definitions
                if "*" not in item.domains
                and any(
                    hostname == domain or hostname.endswith(f".{domain}") for domain in item.domains
                )
            ),
            self.get(PortalKind.COMPANY_CAREERS),
        )
        haystack = " ".join([visible_text, *control_labels]).casefold()
        candidates = [
            rule
            for rule in definition.fingerprints
            if page_type is None or rule.page_type == page_type
        ]
        if not candidates:
            raise PortalCatalogError(
                f"{definition.display_name} does not recognize page type {page_type}"
            )
        scored = [
            (
                len([signal for signal in rule.required_signals if signal.casefold() in haystack])
                / len(rule.required_signals),
                rule,
            )
            for rule in candidates
        ]
        confidence, rule = max(scored, key=lambda item: item[0])
        if confidence < rule.minimum_confidence:
            raise PortalCatalogError(
                "Portal fingerprint confidence "
                f"{confidence:.2f} is below {rule.minimum_confidence:.2f}"
            )
        tied = [candidate for score, candidate in scored if score == confidence]
        if page_type is None and len(tied) > 1:
            names = ", ".join(sorted(candidate.page_type for candidate in tied))
            raise PortalCatalogError(f"Portal fingerprint is ambiguous across {names}")
        matched = [signal for signal in rule.required_signals if signal.casefold() in haystack]
        intervention = rule.capability in {
            PortalCapability.LOGIN,
            PortalCapability.MFA,
            PortalCapability.CAPTCHA,
            PortalCapability.SUBMISSION,
        }
        return PortalPageMatch(
            portal=definition.kind,
            capability=rule.capability,
            page_type=rule.page_type,
            confidence=confidence,
            matched_signals=matched,
            page_fingerprint=page_fingerprint,
            requires_user_intervention=intervention,
        )

    def run_replays(self, cases: list[PortalReplayCase]) -> list[PortalRegressionMetric]:
        results: list[PortalRegressionMetric] = []
        for definition in self._definitions:
            portal_cases = [case for case in cases if case.portal is definition.kind]
            passed = 0
            confirmation_cases = 0
            confirmation_passed = 0
            false_positives = 0
            for case in portal_cases:
                if not case.sanitized:
                    raise PortalCatalogError(f"Replay case {case.id} is not sanitized")
                try:
                    match = self.identify(
                        url=case.url,
                        page_type=case.page_type,
                        visible_text=case.visible_text,
                        control_labels=case.control_labels,
                        page_fingerprint=f"replay:{case.id}",
                    )
                except PortalCatalogError:
                    continue
                case_passed = (
                    match.portal is case.portal
                    and match.capability is case.expected_capability
                    and match.page_type == case.page_type
                )
                if case.expected_confirmation is not None:
                    confirmation_cases += 1
                    confirmed = self.verify_confirmation(
                        case.portal,
                        page_type=case.page_type,
                        visible_text=case.visible_text,
                        confirmation_identifier=case.confirmation_identifier,
                    )
                    confirmation_passed += int(confirmed is case.expected_confirmation)
                    false_positives += int(confirmed and not case.expected_confirmation)
                    case_passed = case_passed and confirmed is case.expected_confirmation
                passed += int(case_passed)
            total = len(portal_cases)
            results.append(
                PortalRegressionMetric(
                    portal=definition.kind,
                    cases=total,
                    passed=passed,
                    fingerprint_accuracy=passed / total if total else 0,
                    confirmation_false_positives=false_positives,
                    confirmation_cases=confirmation_cases,
                    confirmation_passed=confirmation_passed,
                    page_types_exercised=sorted({case.page_type for case in portal_cases}),
                    capabilities_exercised=sorted(
                        {case.expected_capability for case in portal_cases},
                        key=lambda item: item.value,
                    ),
                    required_replay_coverage=(
                        {case.page_type for case in portal_cases} >= _REQUIRED_REPLAY_PAGE_TYPES
                        and confirmation_cases >= 2
                        and confirmation_passed == confirmation_cases
                        and false_positives == 0
                    ),
                    support_status=definition.support_status,
                )
            )
        return results

    def verify_confirmation(
        self,
        kind: PortalKind,
        *,
        page_type: str,
        visible_text: str,
        confirmation_identifier: str | None,
    ) -> bool:
        rule = self.get(kind).confirmation
        if page_type not in rule.page_types:
            return False
        lowered = visible_text.casefold()
        if not any(pattern.casefold() in lowered for pattern in rule.required_text_patterns):
            return False
        return bool(confirmation_identifier) if rule.require_identifier else True
