"""Bind a supervised Greenhouse start to exact current readiness evidence."""

from pathlib import PurePath
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
from job_apply_pro.domain.greenhouse_form import (
    GREENHOUSE_FORM_ACTION_POLICY_VERSION,
    GREENHOUSE_FORM_NAVIGATION_CONFIRMATION,
    GREENHOUSE_FORM_UPLOAD_CONFIRMATION,
    GreenhouseFormAction,
    GreenhouseFormActionApproval,
    GreenhouseFormActionPreview,
    GreenhouseFormActionRequest,
)
from job_apply_pro.domain.knowledge import CandidateDocumentVersionRecord
from job_apply_pro.domain.portals import (
    PortalKind,
    SupervisedPortalRunCreate,
    SupervisedPortalRunSnapshot,
)
from job_apply_pro.services.job_readiness import JobReadinessService, fingerprint
from job_apply_pro.storage.repository_contracts import CandidateKnowledgeRepositoryProtocol


class ReviewedGreenhousePortalProtocol(Protocol):
    def start_reviewed_greenhouse(
        self, command: SupervisedPortalRunCreate, review_fingerprint: str
    ) -> SupervisedPortalRunSnapshot: ...

    def get(self, run_id: str) -> SupervisedPortalRunSnapshot: ...

    def upload_reviewed_greenhouse_document(
        self,
        run_id: str,
        *,
        form_review_fingerprint: str,
        control_key: str,
        document: CandidateDocumentVersionRecord,
    ) -> SupervisedPortalRunSnapshot: ...

    def navigate_reviewed_greenhouse_form(
        self,
        run_id: str,
        *,
        form_review_fingerprint: str,
        control_key: str,
    ) -> SupervisedPortalRunSnapshot: ...


_FORM_ACTIONS = {
    GreenhouseFormAction.REVIEW_DOCUMENT_UPLOAD,
    GreenhouseFormAction.REVIEW_NAVIGATION,
}
_DOCUMENT_SUFFIXES = {".doc", ".docx", ".pdf"}


class GreenhouseApplicationService:
    def __init__(
        self,
        readiness: JobReadinessService,
        supervised: ReviewedGreenhousePortalProtocol | None = None,
        knowledge: CandidateKnowledgeRepositoryProtocol | None = None,
    ) -> None:
        self._readiness = readiness
        self._supervised = supervised
        self._knowledge = knowledge

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

    def preview_form_action(
        self, command: GreenhouseFormActionRequest
    ) -> GreenhouseFormActionPreview:
        if self._supervised is None or self._knowledge is None:
            raise GreenhouseApplicationLaunchError(
                "Reviewed Greenhouse form actions are unavailable"
            )
        if command.action not in _FORM_ACTIONS:
            raise GreenhouseApplicationLaunchError(
                "Only reviewed Greenhouse document upload or stage navigation is available"
            )
        launch = self.preview(command.application_id)
        run = self._supervised.get(command.run_id)
        if run.portal is not PortalKind.GREENHOUSE or run.workflow_id != launch.workflow_id:
            raise GreenhouseApplicationLaunchError(
                "The supervised Greenhouse run does not match this reviewed application"
            )
        assessment = run.greenhouse_form
        if assessment is None or assessment.review_fingerprint != command.form_review_fingerprint:
            raise GreenhouseApplicationLaunchError(
                "The Greenhouse form changed; capture and review the current page again"
            )
        controls = [
            control for control in assessment.controls if control.control_key == command.control_key
        ]
        if len(controls) != 1 or controls[0].action is not command.action:
            raise GreenhouseApplicationLaunchError(
                "The reviewed Greenhouse control is missing, ambiguous, or no longer actionable"
            )
        control = controls[0]
        document: CandidateDocumentVersionRecord | None = None
        if command.action is GreenhouseFormAction.REVIEW_DOCUMENT_UPLOAD:
            document = self._knowledge.get_version_record(launch.selected_document_version_id)
            if document is None:
                raise GreenhouseApplicationLaunchError(
                    "The exact reviewed document version is unavailable"
                )
            if (
                PurePath(document.file_name).name != document.file_name
                or PurePath(document.file_name).suffix.casefold() not in _DOCUMENT_SUFFIXES
            ):
                raise GreenhouseApplicationLaunchError(
                    "The reviewed document filename is not supported for Greenhouse upload"
                )
        elif (
            not assessment.ready_to_advance
            or assessment.navigation_control_key != command.control_key
        ):
            raise GreenhouseApplicationLaunchError(
                "The reviewed Greenhouse page is not ready for stage navigation"
            )
        payload: dict[str, object] = {
            **command.model_dump(mode="json"),
            "workflow_id": launch.workflow_id,
            "page_fingerprint": run.page_fingerprint,
            "page_type": assessment.page_type,
            "stage": assessment.stage.value,
            "control_label": control.label,
            "selected_document_version_id": document.id if document else None,
            "selected_document_file_name": document.file_name if document else None,
            "selected_document_sha256": document.sha256 if document else None,
            "policy_version": GREENHOUSE_FORM_ACTION_POLICY_VERSION,
        }
        notice = (
            "This will stage the exact reviewed immutable document only for one confirmed "
            "Greenhouse upload, verify the observed filename, and remove staged plaintext."
            if document
            else "This will activate one exact reviewed Greenhouse navigation control and "
            "require a verified transition to a recognized later stage."
        )
        return GreenhouseFormActionPreview.model_validate(
            payload | {"preview_fingerprint": fingerprint(payload), "notice": notice}
        )

    def execute_form_action(
        self, approval: GreenhouseFormActionApproval
    ) -> SupervisedPortalRunSnapshot:
        expected_confirmation = {
            GreenhouseFormAction.REVIEW_DOCUMENT_UPLOAD: GREENHOUSE_FORM_UPLOAD_CONFIRMATION,
            GreenhouseFormAction.REVIEW_NAVIGATION: GREENHOUSE_FORM_NAVIGATION_CONFIRMATION,
        }.get(approval.action)
        if expected_confirmation is None or approval.confirmation_phrase != expected_confirmation:
            raise GreenhouseApplicationLaunchError(
                "Reviewed Greenhouse form action confirmation is required"
            )
        current = self.preview_form_action(
            GreenhouseFormActionRequest.model_validate(
                approval.model_dump(exclude={"preview_fingerprint", "confirmation_phrase"})
            )
        )
        if current.preview_fingerprint != approval.preview_fingerprint:
            raise GreenhouseApplicationLaunchError(
                "Greenhouse form action evidence changed; review the current action again"
            )
        if self._supervised is None:
            raise GreenhouseApplicationLaunchError(
                "Reviewed Greenhouse form actions are unavailable"
            )
        if approval.action is GreenhouseFormAction.REVIEW_NAVIGATION:
            return self._supervised.navigate_reviewed_greenhouse_form(
                approval.run_id,
                form_review_fingerprint=approval.form_review_fingerprint,
                control_key=approval.control_key,
            )
        if self._knowledge is None or current.selected_document_version_id is None:
            raise GreenhouseApplicationLaunchError("Reviewed Greenhouse document is unavailable")
        document = self._knowledge.get_version_record(current.selected_document_version_id)
        if (
            document is None
            or document.file_name != current.selected_document_file_name
            or document.sha256 != current.selected_document_sha256
        ):
            raise GreenhouseApplicationLaunchError(
                "The reviewed Greenhouse document changed before upload"
            )
        return self._supervised.upload_reviewed_greenhouse_document(
            approval.run_id,
            form_review_fingerprint=approval.form_review_fingerprint,
            control_key=approval.control_key,
            document=document,
        )
