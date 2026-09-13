from job_apply_pro.domain.job_discovery import (
    GreenhouseImportRequest,
    GreenhouseImportResult,
    GreenhouseReviewRequest,
)
from job_apply_pro.portals.greenhouse import (
    GreenhousePublicBoardClient,
    GreenhouseSourceUnavailableError,
)
from job_apply_pro.storage.job_discovery_repository import (
    GreenhouseDiscoveryRepository,
    GreenhouseImportConflictError,
)


class GreenhouseDiscoveryService:
    def __init__(
        self,
        repository: GreenhouseDiscoveryRepository,
        client: GreenhousePublicBoardClient,
    ) -> None:
        self._repository = repository
        self._client = client

    def import_job(self, command: GreenhouseImportRequest) -> GreenhouseImportResult:
        if not self._repository.profile_exists(command.profile_id):
            raise GreenhouseImportConflictError("Select an existing local profile before importing")
        # Deliberately construct a public-only command; candidate identifiers never
        # enter the provider client or its network request arguments.
        try:
            review = self._client.review_job(
                GreenhouseReviewRequest(
                    board_token=command.board_token,
                    posting_id=command.posting_id,
                )
            )
        except GreenhouseSourceUnavailableError:
            return GreenhouseImportResult(
                outcome="SOURCE_UNAVAILABLE",
                notice="The posting is no longer available for public import.",
            )
        if review.review_fingerprint != command.review_fingerprint:
            return GreenhouseImportResult(
                outcome="STALE_REVIEW",
                notice="The public posting changed since this preview. "
                "Review it again before saving.",
            )
        return self._repository.import_reviewed(command.profile_id, review)
