from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from pydantic import SecretStr

from job_apply_pro.ai.configuration import AIConfiguration
from job_apply_pro.ai.media_journal import MediaJournal
from job_apply_pro.ai.providers import (
    AIProviderMediaRetentionError,
    AIProviderRuntime,
    GeminiProvider,
)
from job_apply_pro.domain.ai import ProviderKind
from job_apply_pro.domain.media_cleanup import MediaCleanupPublicRecord, MediaCleanupState
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.storage.media_cleanup_repository import MediaCleanupRepository

LEASE = timedelta(minutes=20)
RECOVERY_TIMEOUT_SECONDS = 15.0
RECOVERY_BATCH_SIZE = 2
RECOVERY_INTERVAL_SECONDS = 60.0
MANUAL_CONFIRMATION = "I VERIFIED PROVIDER MEDIA CLEANUP"


def utc_now() -> datetime:
    return datetime.now(UTC)


def account_fingerprint(runtime: AIProviderRuntime, cipher: SensitiveDataCipher) -> str:
    if runtime.api_key is None:
        raise ValueError("Media cleanup credentials are unavailable")
    # blind_index normalizes text. Hash EXACT key bytes first, preserving case and
    # whitespace distinctions without persisting an unkeyed credential digest.
    credential_digest = hashlib.sha256(runtime.api_key.get_secret_value().encode()).hexdigest()
    return cipher.blind_index(
        f"{runtime.definition.kind.value}:"
        f"{str(runtime.definition.base_url).rstrip('/')}:{credential_digest}",
        context="ai-media-account",
    )


class DurableMediaJournal:
    def __init__(
        self,
        repository: MediaCleanupRepository,
        provider_id: str,
        fingerprint: str,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._repository = repository
        self._provider_id = provider_id
        self._fingerprint = fingerprint
        self._clock = clock
        self._token = str(uuid4())
        self._resources: dict[str, str | None] = {}

    def begin(self) -> str:
        try:
            now = self._clock()
            record = self._repository.create(
                self._provider_id, self._fingerprint, self._token, now, now + LEASE
            )
            self._resources[record.id] = None
            return record.id
        except Exception as error:
            raise AIProviderMediaRetentionError("Durable media ownership is unavailable") from error

    def register(self, record_id: str, name: str) -> None:
        # Retain local cleanup ownership even if the committed encrypted write fails.
        self._resources[record_id] = name
        try:
            now = self._clock()
            self._repository.register_resource(record_id, self._token, name, now, now + LEASE)
        except Exception as error:
            raise AIProviderMediaRetentionError("Durable media registration failed") from error

    def abandon_before_upload(self, record_id: str) -> None:
        try:
            self._repository.abandon_before_upload(record_id, self._token, self._clock())
            del self._resources[record_id]
        except Exception as error:
            raise AIProviderMediaRetentionError(
                "Durable media intent could not be closed"
            ) from error

    def renew(self) -> None:
        try:
            for record_id in self._resources:
                now = self._clock()
                self._repository.renew(record_id, self._token, now, now + LEASE)
        except Exception as error:
            raise AIProviderMediaRetentionError(
                "Durable media ownership expired or changed"
            ) from error

    def cleanup(self, delete: Callable[[str], None]) -> None:
        unresolved = False
        for record_id, local_name in reversed(self._resources.items()):
            try:
                record = self._repository.relinquish(record_id, self._token, self._clock())
                if record.state is MediaCleanupState.MANUAL_REVIEW:
                    # A local name may exist after an encrypted registration failure.
                    if local_name is not None:
                        delete(local_name)
                    unresolved = True
                    continue
                now = self._clock()
                claimed = self._repository.claim_recovery(record_id, self._token, now, now + LEASE)
            except Exception:
                # The durable lease may have expired while finalization was in flight.
                # Delete ONLY the exact locally observed name; do not clear the journal
                # or infer success without the required ownership transition.
                if local_name is not None:
                    with suppress(Exception):
                        delete(local_name)
                unresolved = True
                continue
            if claimed is None or claimed.resource_name is None:
                unresolved = True
                continue
            try:
                delete(claimed.resource_name)
                self._repository.mark_deleted(record_id, self._token, self._clock())
            except Exception:
                unresolved = True
                try:
                    now = self._clock()
                    self._repository.mark_retry(
                        record_id, self._token, "DELETE_FAILED", now, now + timedelta(minutes=1)
                    )
                except Exception:
                    # The committed claim remains recoverable when its lease expires.
                    pass
        if unresolved:
            raise AIProviderMediaRetentionError(
                "Gemini uploaded media deletion could not be confirmed; "
                "recovery or review is required"
            )


class MediaCleanupService:
    def __init__(
        self,
        repository: MediaCleanupRepository,
        cipher: SensitiveDataCipher,
        config_json: SecretStr | None,
        *,
        clock: Callable[[], datetime] = utc_now,
        provider_factory: Callable[[AIProviderRuntime], GeminiProvider] = GeminiProvider,
    ) -> None:
        self._repository = repository
        self._cipher = cipher
        self._config_json = config_json
        self._clock = clock
        self._provider_factory = provider_factory

    def journal_factory(self, runtime: AIProviderRuntime) -> Callable[[], MediaJournal]:
        # No key access, DB mutation, or networking during registry/status construction.
        def create() -> MediaJournal:
            try:
                fingerprint = account_fingerprint(runtime, self._cipher)
                return DurableMediaJournal(
                    self._repository, runtime.definition.id, fingerprint, clock=self._clock
                )
            except Exception as error:
                raise AIProviderMediaRetentionError(
                    "Durable media encryption is unavailable"
                ) from error

        return create

    def list_public(self) -> list[MediaCleanupPublicRecord]:
        return self._repository.list_public()

    def resolve_manual(self, record_id: str, expected_updated_at: datetime) -> None:
        self._repository.resolve_manual(record_id, expected_updated_at, self._clock())

    def recover(self) -> None:
        config = (
            AIConfiguration.model_validate_json(self._config_json.get_secret_value())
            if self._config_json is not None
            else AIConfiguration(providers=[], models=[], policies=[])
        )
        runtimes = {
            item.definition.id: AIProviderRuntime(definition=item.definition, api_key=item.api_key)
            for item in config.providers
            if item.definition.kind is ProviderKind.GEMINI and item.definition.enabled
        }
        accounts: dict[str, AIProviderRuntime] = {}
        for runtime in runtimes.values():
            try:
                fingerprint = account_fingerprint(runtime, self._cipher)
            except Exception:
                # Missing/invalid credentials or key access must not starve other
                # providers or no-network classification of unknown uploads.
                continue
            accounts[fingerprint] = runtime
        candidates = self._repository.list_recovery_candidates(
            self._clock(), limit=100, accounts=set(accounts), include_unknown=True
        )
        attempted = 0
        for candidate in candidates:
            token = str(uuid4())
            now = self._clock()
            try:
                if not candidate.known_resource:
                    # Unknown outcome needs no credentials/decryption/network to
                    # classify for manual review; it must never trigger bulk listing.
                    self._repository.claim_recovery(candidate.id, token, now, now + LEASE)
                    continue
                matched_runtime = accounts.get(candidate.account_fingerprint)
                if matched_runtime is None:
                    continue
                provider = self._provider_factory(matched_runtime)  # validates fixed HTTPS origin
                record = self._repository.claim_recovery(candidate.id, token, now, now + LEASE)
                if record is None or record.resource_name is None:
                    continue
                attempted += 1
                try:
                    provider.delete_uploaded_media(record.resource_name, RECOVERY_TIMEOUT_SECONDS)
                    self._repository.mark_deleted(record.id, token, self._clock())
                except Exception:
                    now = self._clock()
                    delay = timedelta(seconds=min(3600, 60 * 2 ** min(record.attempts, 6)))
                    self._repository.mark_retry(record.id, token, "DELETE_FAILED", now, now + delay)
            except Exception:
                # A broken row/configuration cannot prevent independent recoveries.
                # Any acquired claim remains eligible again after lease expiry.
                pass
            if attempted >= RECOVERY_BATCH_SIZE:
                break


async def run_media_cleanup_worker(
    service_factory: Callable[[], MediaCleanupService], stop: asyncio.Event
) -> None:
    """Deletion-only startup/periodic recovery; no blocking work on the event loop."""
    while not stop.is_set():
        # No exception text: it could contain an API key or a remote resource.
        # Durable records remain visible; a later cycle can retry safely.
        with suppress(Exception):
            await asyncio.to_thread(lambda: service_factory().recover())
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=RECOVERY_INTERVAL_SECONDS)
