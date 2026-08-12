from __future__ import annotations

import re
from urllib.parse import quote_plus, urljoin, urlsplit

import httpx
from pydantic import AnyHttpUrl

from job_apply_pro.domain.browser import (
    BrowserAction,
    BrowserActionKind,
    BrowserObservation,
    BrowserPermission,
    BrowserVerification,
    ConfirmationState,
    LocatorStrategy,
    SemanticLocator,
    VerificationKind,
)
from job_apply_pro.domain.portals import (
    PortalFieldMapping,
    PortalJobPosting,
    SubmissionEvidence,
)
from job_apply_pro.domain.workflow import utc_now


class PortalContractError(ValueError):
    pass


def _loopback_origin(origin: str) -> str:
    parsed = urlsplit(origin)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise PortalContractError("The reference ATS accepts loopback fixture origins only")
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{parsed.hostname}{port}"


def _lines(observation: BrowserObservation) -> list[str]:
    return [line.strip() for line in observation.visible_text.splitlines() if line.strip()]


def _value_after(lines: list[str], label: str) -> str:
    try:
        index = lines.index(label)
        value = lines[index + 1]
    except (ValueError, IndexError) as error:
        raise PortalContractError(f"Reference ATS job page is missing {label}") from error
    if not value:
        raise PortalContractError(f"Reference ATS job page has an empty {label}")
    return value


class ReferenceAtsAdapter:
    source = "reference-ats"

    def search_url(self, origin: str, query: str) -> AnyHttpUrl:
        safe_origin = _loopback_origin(origin)
        return AnyHttpUrl(f"{safe_origin}/jobs?query={quote_plus(query)}")

    def discover_jobs(self, origin: str, query: str) -> list[PortalJobPosting]:
        safe_origin = _loopback_origin(origin)
        try:
            response = httpx.get(
                f"{safe_origin}/api/jobs",
                params={"query": query},
                timeout=10,
                follow_redirects=False,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise PortalContractError("Reference ATS discovery endpoint failed") from error
        if not isinstance(payload, list):
            raise PortalContractError("Reference ATS discovery response must be a list")
        jobs: list[PortalJobPosting] = []
        for value in payload[:100]:
            if not isinstance(value, dict):
                raise PortalContractError("Reference ATS discovery returned an invalid job")
            job = PortalJobPosting.model_validate(value)
            if _loopback_origin(str(job.source_url)) != safe_origin:
                raise PortalContractError("Reference ATS job URL changed origin")
            jobs.append(job)
        return jobs

    def first_job_url(self, observation: BrowserObservation) -> AnyHttpUrl:
        if observation.page_type != "JOB_SEARCH_RESULTS":
            raise PortalContractError("Expected a reference ATS search-results page")
        for control in observation.controls:
            href = control.href
            if control.tag == "a" and "/jobs/" in href:
                return AnyHttpUrl(urljoin(observation.url, href))
        raise PortalContractError("Reference ATS search returned no supported job links")

    def extract_job(self, observation: BrowserObservation) -> PortalJobPosting:
        if observation.page_type != "JOB_DETAIL":
            raise PortalContractError("Expected a reference ATS job-detail page")
        lines = _lines(observation)
        requirements: list[str] = []
        if "Requirements" in lines:
            start = lines.index("Requirements") + 1
            stop_labels = {"Apply now", "Return to jobs"}
            requirements = [value for value in lines[start:] if value not in stop_labels]
        return PortalJobPosting(
            external_id=_value_after(lines, "Job ID"),
            employer=_value_after(lines, "Employer"),
            title=_value_after(lines, "Title"),
            location=_value_after(lines, "Location"),
            description=_value_after(lines, "Description"),
            requirements=requirements,
            source_url=AnyHttpUrl(observation.url),
        )

    def map_fields(self, observation: BrowserObservation) -> list[PortalFieldMapping]:
        mappings: list[PortalFieldMapping] = []
        for control in observation.controls:
            canonical = control.canonical_field
            label = control.label
            if isinstance(canonical, str) and canonical and isinstance(label, str) and label:
                mappings.append(
                    PortalFieldMapping(
                        page_type=observation.page_type,
                        canonical_field=canonical,
                        label=label,
                        required=control.required,
                    )
                )
        return mappings

    def navigate(self, url: AnyHttpUrl, result_path: str) -> BrowserAction:
        return BrowserAction(
            kind=BrowserActionKind.NAVIGATE,
            url=url,
            intended_result=f"Navigate to {result_path}",
            verification=BrowserVerification(
                kind=VerificationKind.URL_CONTAINS,
                value=result_path,
            ),
        )

    def fill(self, label: str, value: str) -> BrowserAction:
        locator = SemanticLocator(strategy=LocatorStrategy.LABEL, value=label)
        return BrowserAction(
            kind=BrowserActionKind.FILL,
            locator=locator,
            value=value,
            intended_result=f"Fill {label}",
            verification=BrowserVerification(
                kind=VerificationKind.VALUE_EQUALS,
                value=value,
                locator=locator,
            ),
        )

    def check(self, label: str) -> BrowserAction:
        return BrowserAction(
            kind=BrowserActionKind.CHECK,
            locator=SemanticLocator(strategy=LocatorStrategy.LABEL, value=label),
            intended_result=f"Check {label}",
        )

    def upload(self, label: str, file_path: str, file_name: str) -> BrowserAction:
        return BrowserAction(
            kind=BrowserActionKind.UPLOAD,
            locator=SemanticLocator(strategy=LocatorStrategy.LABEL, value=label),
            file_path=file_path,
            intended_result=f"Upload approved document {file_name}",
            verification=BrowserVerification(
                kind=VerificationKind.TEXT_VISIBLE,
                value=file_name,
            ),
        )

    def click(self, name: str, result_path: str) -> BrowserAction:
        return BrowserAction(
            kind=BrowserActionKind.CLICK,
            locator=SemanticLocator(
                strategy=LocatorStrategy.ROLE,
                value="button",
                name=name,
            ),
            intended_result=f"Continue to {result_path}",
            verification=BrowserVerification(
                kind=VerificationKind.URL_CONTAINS,
                value=result_path,
            ),
        )

    def submit_action(self) -> BrowserAction:
        return BrowserAction(
            kind=BrowserActionKind.CLICK,
            locator=SemanticLocator(
                strategy=LocatorStrategy.ROLE,
                value="button",
                name="Submit application",
            ),
            intended_result="Submit the reviewed reference ATS application",
            verification=BrowserVerification(
                kind=VerificationKind.URL_CONTAINS,
                value="/application/confirmation",
            ),
            permission=BrowserPermission.ELEVATED,
            confirmation=ConfirmationState.CONFIRMED,
        )

    def confirmation_evidence(self, observation: BrowserObservation) -> SubmissionEvidence:
        if observation.page_type != "CONFIRMATION":
            raise PortalContractError("Submission did not reach a confirmation page")
        match = re.search(
            r"Confirmation (?:number|code):?\s*([A-Za-z0-9-]{4,200})",
            observation.visible_text,
            flags=re.IGNORECASE,
        )
        if match is None:
            raise PortalContractError("Confirmation page has no approved verification signal")
        signal = match.group(0).strip()
        return SubmissionEvidence(
            confirmation_code=match.group(1),
            confirmation_url=observation.url,
            page_fingerprint=observation.page_fingerprint,
            visible_signal=signal,
            verified_at=utc_now(),
        )
