"""Bind a supervised Greenhouse start to exact current readiness evidence."""

from typing import Protocol
from urllib.parse import urlsplit

from pydantic import AnyHttpUrl

from job_apply_pro.domain.greenhouse_application import (
    GREENHOUSE_APPLICATION_LAUNCH_CONFIRMATION,
    GREENHOUSE_APPLICATION_LAUNCH_POLICY,
    GreenhouseApplicationLaunchApproval,
    GreenhouseApplicationLaunchError,
    GreenhouseApplicationLaunchPreview,
)
from job_apply_pro.domain.portals import (
    PortalKind,
    SupervisedPortalRunCreate,
    SupervisedPortalRunSnapshot,
)
from job_apply_pro.services.job_readiness import JobReadinessService, fingerprint


class ReviewedGreenhousePortalProtocol(Protocol):
    def start_reviewed_greenhouse(
        self, command: SupervisedPortalRunCreate, review_fingerprint: str
    ) -> SupervisedPortalRunSnapshot: ...


class GreenhouseApplicationService:
    def __init__(
        self,
        readiness: JobReadinessService,
        supervised: ReviewedGreenhousePortalProtocol | None = None,
    ) -> None:
        self._readiness = readiness
        self._supervised = supervised

    def preview(self, application_id: str) -> GreenhouseApplicationLaunchPreview:
        snapshot = self._readiness.snapshot(application_id)
        if (
            not snapshot.supported
            or snapshot.status != "READY"
            or snapshot.source is None
            or snapshot.source_fingerprint is None
            or snapshot.requirements_review is None
            or snapshot.qualification_review is None
            or snapshot.selection_review is None
        ):
            raise GreenhouseApplicationLaunchError(
                "Complete the current reviewed Greenhouse readiness chain before launch"
            )
        source_url = snapshot.source.source_url
        if not snapshot.source.navigation_supported or source_url is None:
            raise GreenhouseApplicationLaunchError(
                "The saved Greenhouse posting has no approved public application URL"
            )
        parsed = urlsplit(source_url)
        host = (parsed.hostname or "").casefold()
        if parsed.scheme != "https" or not (
            host == "greenhouse.io" or host.endswith(".greenhouse.io")
        ):
            raise GreenhouseApplicationLaunchError(
                "The saved Greenhouse application URL is outside the approved HTTPS domain"
            )
        origin = f"https://{host}{f':{parsed.port}' if parsed.port else ''}"
        payload = {
            "application_id": snapshot.application_id,
            "workflow_id": snapshot.workflow_id,
            "profile_id": snapshot.profile_id,
            "job_id": snapshot.job_id,
            "employer": snapshot.source.employer,
            "title": snapshot.source.title,
            "start_url": source_url,
            "start_origin": origin,
            "selected_document_version_id": snapshot.selection_review.document_version_id,
            "source_fingerprint": snapshot.source_fingerprint,
            "requirements_review_id": snapshot.requirements_review.id,
            "qualification_review_id": snapshot.qualification_review.id,
            "selection_review_id": snapshot.selection_review.id,
            "policy_version": GREENHOUSE_APPLICATION_LAUNCH_POLICY,
        }
        return GreenhouseApplicationLaunchPreview.model_validate(
            payload
            | {
                "review_fingerprint": fingerprint(payload),
                "notice": "This opens the exact reviewed public Greenhouse posting in a "
                "visible supervised browser. It does not fill, attest, sign, or submit.",
            }
        )

    def start(self, approval: GreenhouseApplicationLaunchApproval) -> SupervisedPortalRunSnapshot:
        if approval.confirmation_phrase != GREENHOUSE_APPLICATION_LAUNCH_CONFIRMATION:
            raise GreenhouseApplicationLaunchError(
                "Reviewed Greenhouse launch confirmation is required"
            )
        current = self.preview(approval.application_id)
        if current.review_fingerprint != approval.review_fingerprint:
            raise GreenhouseApplicationLaunchError(
                "Greenhouse launch evidence changed; review the current launch again"
            )
        if self._supervised is None:
            raise GreenhouseApplicationLaunchError("Supervised Greenhouse launch is unavailable")
        return self._supervised.start_reviewed_greenhouse(
            SupervisedPortalRunCreate(
                workflow_id=current.workflow_id,
                portal=PortalKind.GREENHOUSE,
                start_url=AnyHttpUrl(current.start_url),
                profile_name=approval.profile_name,
                engine=approval.engine,
                allowed_origins=[],
            ),
            current.review_fingerprint,
        )
