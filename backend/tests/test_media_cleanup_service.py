from __future__ import annotations

import asyncio
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Table, create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from job_apply_pro.ai.configuration import build_ai_registry
from job_apply_pro.ai.providers import (
    AIProviderMediaRetentionError,
    AIProviderRuntime,
    GeminiProvider,
)
from job_apply_pro.api.routes.ai import get_media_cleanup_service
from job_apply_pro.config import get_settings
from job_apply_pro.domain.ai import AIInputPart, AIProviderRequest
from job_apply_pro.main import create_app
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.security.keys import StaticKeyProvider
from job_apply_pro.services.media_cleanup import (
    LEASE,
    MANUAL_CONFIRMATION,
    MediaCleanupService,
    account_fingerprint,
    run_media_cleanup_worker,
)
from job_apply_pro.storage.media_cleanup_repository import MediaCleanupRepository
from job_apply_pro.storage.models import MediaCleanupRow

_HOST = "https://generativelanguage.googleapis.com"
_NAME = "files/recovery-fixture"


def _request() -> AIProviderRequest:
    return AIProviderRequest(
        model="gemini-fixture",
        system_instruction="Review",
        user_content="Describe",
        input_parts=[
            AIInputPart(kind="media", data=b"\x89PNG\r\n\x1a\nfixture", mime_type="image/png")
        ],
        media_upload_consent=True,
        timeout_seconds=5,
    )


@dataclass
class RecoveryHarness:
    repository: MediaCleanupRepository
    cipher: SensitiveDataCipher
    factory: sessionmaker[Session]
    now: datetime = field(default_factory=lambda: datetime(2026, 9, 12, tzinfo=UTC))
    events: list[httpx.Request] = field(default_factory=list)
    delete_status: int = 204
    finalization_fails: bool = False
    expire_interaction: bool = False

    @property
    def runtime(self) -> AIProviderRuntime:
        return AIProviderRuntime.model_validate(
            {
                "definition": {
                    "id": "gemini",
                    "kind": "GEMINI",
                    "external": True,
                    "base_url": f"{_HOST}/v1beta",
                },
                "api_key": "synthetic-MixedCase-key",
            }
        )

    def service(self, runtime: AIProviderRuntime | None = None) -> MediaCleanupService:
        import json

        value = runtime or self.runtime
        config = SecretStr(
            json.dumps(
                {
                    "providers": [
                        {
                            "definition": value.definition.model_dump(mode="json"),
                            "api_key": cast(SecretStr, value.api_key).get_secret_value(),
                        }
                    ],
                    "models": [],
                    "policies": [],
                }
            )
        )
        return MediaCleanupService(
            self.repository,
            self.cipher,
            config,
            clock=lambda: self.now,
            provider_factory=lambda runtime: GeminiProvider(
                runtime, transport=httpx.MockTransport(self.handle)
            ),
        )

    def provider(self) -> GeminiProvider:
        return GeminiProvider(
            self.runtime,
            transport=httpx.MockTransport(self.handle),
            journal_factory=self.service().journal_factory(self.runtime),
        )

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.events.append(request)
        if request.method == "DELETE":
            assert request.url.path == f"/v1beta/{_NAME}"
            assert request.headers["x-goog-api-key"] == "synthetic-MixedCase-key"
            return httpx.Response(self.delete_status)
        command = request.headers.get("x-goog-upload-command")
        if command == "start":
            # Observe a COMMITTED intent from an independent session before I/O.
            with self.factory() as session:
                assert session.scalar(select(MediaCleanupRow.state)) == "UPLOADING"
            return httpx.Response(
                200, headers={"x-goog-upload-url": f"{_HOST}/upload/v1beta/files?upload_id=fixture"}
            )
        if command == "upload, finalize":
            if self.finalization_fails:
                raise httpx.ReadTimeout("SENSITIVE ERROR MUST NOT BE PERSISTED")
            return httpx.Response(
                200,
                json={
                    "file": {
                        "name": _NAME,
                        "uri": f"{_HOST}/v1beta/{_NAME}",
                        "mimeType": "image/png",
                        "state": "ACTIVE",
                    }
                },
            )
        assert request.url.path == "/v1beta/interactions"
        if self.expire_interaction:
            self.now += LEASE + timedelta(seconds=1)
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "steps": [
                    {"type": "model_output", "content": [{"type": "text", "text": "Reviewed"}]},
                ],
            },
        )

    def seed(self, *, known: bool = True, pending: bool = False) -> str:
        journal = self.service().journal_factory(self.runtime)()
        record_id = journal.begin()
        if known:
            journal.register(record_id, _NAME)
        if pending:
            with self.factory() as session:
                row = session.get(MediaCleanupRow, record_id)
                assert row is not None
                token = row.owner_token
            self.repository.relinquish(record_id, token, self.now)
        return record_id


@pytest.fixture
def harness(tmp_path: Path) -> Iterator[RecoveryHarness]:
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'journal.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    cast(Table, MediaCleanupRow.__table__).create(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    cipher = SensitiveDataCipher(StaticKeyProvider(b"r" * 32))
    yield RecoveryHarness(MediaCleanupRepository(factory, cipher), cipher, factory)
    engine.dispose()


def test_real_provider_persists_intent_and_clears_encrypted_resource_after_delete(
    harness: RecoveryHarness,
) -> None:
    assert harness.provider().complete(_request()).content == "Reviewed"
    assert [r.method for r in harness.events] == ["POST", "POST", "POST", "DELETE"]
    assert harness.repository.list_public() == []
    with harness.factory() as session:
        row = session.scalar(select(MediaCleanupRow))
        assert row is not None and row.state == "DELETED"
        assert row.reason == "DELETION_CONFIRMED" and row.encrypted_resource is None


def test_missing_journal_is_fail_closed_before_network(harness: RecoveryHarness) -> None:
    provider = GeminiProvider(harness.runtime, transport=httpx.MockTransport(harness.handle))
    with pytest.raises(AIProviderMediaRetentionError, match="durable cleanup storage"):
        provider.complete(_request())
    assert harness.events == []


def test_failed_intent_commit_stops_before_network(
    harness: RecoveryHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("storage unavailable")

    monkeypatch.setattr(harness.repository, "create", fail)
    with pytest.raises(AIProviderMediaRetentionError, match="ownership is unavailable"):
        harness.provider().complete(_request())
    assert harness.events == []


def test_failed_registration_still_deletes_known_local_file_and_retains_uncertainty(
    harness: RecoveryHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("storage unavailable")

    monkeypatch.setattr(harness.repository, "register_resource", fail)
    with pytest.raises(AIProviderMediaRetentionError, match="registration failed"):
        harness.provider().complete(_request())
    assert [r.method for r in harness.events] == ["POST", "POST", "DELETE"]
    record = harness.repository.list_public()[0]
    assert record.state == "MANUAL_REVIEW" and not record.known_resource


def test_unknown_finalization_blocks_further_uploads_without_saving_exception_or_bytes(
    harness: RecoveryHarness,
) -> None:
    harness.finalization_fails = True
    with pytest.raises(AIProviderMediaRetentionError):
        harness.provider().complete(_request())
    assert len(harness.events) == 2
    record = harness.repository.list_public()[0]
    assert record.state == "MANUAL_REVIEW" and record.reason == "UNKNOWN_UPLOAD"
    with pytest.raises(AIProviderMediaRetentionError):
        harness.provider().complete(_request())
    assert len(harness.events) == 2
    public = record.model_dump_json()
    assert "synthetic-MixedCase-key" not in public and "SENSITIVE" not in public
    assert "resource_name" not in public and "owner_token" not in public


def test_restart_deletes_only_expired_known_upload_with_no_inference_or_upload(
    harness: RecoveryHarness,
) -> None:
    harness.seed()
    harness.service().recover()
    assert harness.events == []  # foreground lease remains active
    harness.now += LEASE + timedelta(seconds=1)
    harness.service().recover()  # new service, same committed database
    assert [r.method for r in harness.events] == ["DELETE"]
    assert harness.repository.list_public() == []
    harness.service().recover()
    assert len(harness.events) == 1


@pytest.mark.parametrize("kind", ["changed", "case_changed", "disabled", "removed"])
def test_account_mismatch_never_sends_delete_or_clears_known_record(
    harness: RecoveryHarness, kind: str
) -> None:
    harness.seed(pending=True)
    runtime = harness.runtime
    if kind in {"changed", "case_changed"}:
        key = "another-secret" if kind == "changed" else "synthetic-mixedcase-key"
        runtime = runtime.model_copy(update={"api_key": SecretStr(key)})
    elif kind == "disabled":
        runtime = runtime.model_copy(
            update={"definition": runtime.definition.model_copy(update={"enabled": False})}
        )
    service = (
        harness.service(runtime)
        if kind != "removed"
        else MediaCleanupService(
            harness.repository, harness.cipher, None, clock=lambda: harness.now
        )
    )
    service.recover()
    assert harness.events == []
    assert harness.repository.list_public()[0].known_resource


def test_expired_unknown_is_manual_without_any_provider_configuration(
    harness: RecoveryHarness,
) -> None:
    harness.seed(known=False)
    harness.now += LEASE + timedelta(seconds=1)
    MediaCleanupService(
        harness.repository, harness.cipher, None, clock=lambda: harness.now
    ).recover()
    assert harness.events == []
    assert harness.repository.list_public()[0].state == "MANUAL_REVIEW"


def test_missing_provider_key_does_not_starve_other_accounts_or_unknowns(
    harness: RecoveryHarness,
) -> None:
    import json

    known_id = harness.seed(pending=True)
    unknown = harness.repository.create(
        "missing-key", "b" * 64, "orphan", harness.now, harness.now + LEASE
    )
    harness.now += LEASE + timedelta(seconds=1)
    service = harness.service()
    config = json.loads(cast(SecretStr, service._config_json).get_secret_value())
    config["providers"].append(
        {
            "definition": harness.runtime.definition.model_copy(
                update={"id": "missing-key"}
            ).model_dump(mode="json"),
            "api_key": None,
        }
    )
    service._config_json = SecretStr(json.dumps(config))
    service.recover()
    remaining = harness.repository.list_public()
    assert len(remaining) == 1 and remaining[0].id == unknown.id
    assert remaining[0].state == "MANUAL_REVIEW"
    assert remaining[0].id != known_id
    assert [request.method for request in harness.events] == ["DELETE"]


def test_failed_delete_retries_only_when_due_and_404_confirms_deletion(
    harness: RecoveryHarness,
) -> None:
    harness.seed(pending=True)
    harness.delete_status = 503
    harness.service().recover()
    record = harness.repository.list_public()[0]
    assert record.state == "DELETE_PENDING" and record.attempts == 1
    assert record.reason == "DELETE_FAILED"
    harness.service().recover()
    assert len(harness.events) == 1
    harness.now += timedelta(minutes=1)
    harness.delete_status = 404
    harness.service().recover()
    assert harness.repository.list_public() == []
    assert [r.method for r in harness.events] == ["DELETE", "DELETE"]


def test_lease_expiry_during_inference_cannot_report_success(harness: RecoveryHarness) -> None:
    harness.expire_interaction = True
    with pytest.raises(AIProviderMediaRetentionError, match="ownership expired"):
        harness.provider().complete(_request())
    assert harness.events[-1].method == "DELETE"  # local exact-name safety cleanup
    assert harness.repository.list_public()  # never guessed durable confirmation
    harness.delete_status = 404
    harness.service().recover()
    assert harness.repository.list_public() == []


def test_fingerprint_preserves_exact_secret_case_and_never_contains_credentials(
    harness: RecoveryHarness,
) -> None:
    one = account_fingerprint(harness.runtime, harness.cipher)
    other = account_fingerprint(
        harness.runtime.model_copy(update={"api_key": SecretStr("synthetic-mixedcase-key")}),
        harness.cipher,
    )
    assert len(one) == 64 and one != other


def test_provider_alias_shares_gate_and_can_recover_same_exact_credentials(
    harness: RecoveryHarness,
) -> None:
    harness.seed(pending=True)
    alias = harness.runtime.model_copy(
        update={
            "definition": harness.runtime.definition.model_copy(update={"id": "renamed-gemini"}),
        }
    )
    assert account_fingerprint(alias, harness.cipher) == account_fingerprint(
        harness.runtime, harness.cipher
    )
    service = harness.service(alias)
    provider = GeminiProvider(
        alias,
        transport=httpx.MockTransport(harness.handle),
        journal_factory=service.journal_factory(alias),
    )
    with pytest.raises(AIProviderMediaRetentionError):
        provider.complete(_request())
    assert harness.events == []
    service.recover()
    assert [r.method for r in harness.events] == ["DELETE"]
    assert harness.repository.list_public() == []


def test_registry_construction_and_public_status_have_no_side_effects(
    harness: RecoveryHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail() -> bytes:
        raise AssertionError("Status must not load encryption keys")

    monkeypatch.setattr(harness.cipher, "blind_index", fail)
    service = harness.service()
    build_ai_registry(service._config_json, journal_factory=service.journal_factory)
    assert service.list_public() == []
    assert harness.events == []


def test_cleanup_routes_auth_validation_and_manual_acknowledgement(
    harness: RecoveryHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    record_id = harness.seed(known=False)
    harness.now += LEASE + timedelta(seconds=1)
    monkeypatch.setenv("JAP_API_TOKEN", "synthetic-local-token")
    get_settings.cache_clear()
    application = create_app()
    application.dependency_overrides[get_media_cleanup_service] = lambda: harness.service()
    client = TestClient(application)
    headers = {"X-Job-Apply-Pro-Token": "synthetic-local-token"}
    base = "/api/v1/ai/media-cleanup"
    try:
        assert client.get(base).status_code == 401
        assert client.post(f"{base}/retry").status_code == 401
        assert client.post(f"{base}/{record_id}/resolve", json={}).status_code == 401
        before = client.get(base, headers=headers).json()["items"][0]
        assert before["state"] == "UPLOADING"  # GET does not recover
        after = client.post(f"{base}/retry", headers=headers).json()["items"][0]
        assert after["state"] == "MANUAL_REVIEW" and harness.events == []
        payload = {"expected_updated_at": after["updated_at"], "confirmation": "wrong"}
        assert (
            client.post(f"{base}/{record_id}/resolve", headers=headers, json=payload).status_code
            == 422
        )
        payload["confirmation"] = MANUAL_CONFIRMATION
        payload["expected_updated_at"] = before["updated_at"]
        assert (
            client.post(f"{base}/{record_id}/resolve", headers=headers, json=payload).status_code
            == 409
        )
        payload["expected_updated_at"] = after["updated_at"]
        response = client.post(f"{base}/{record_id}/resolve", headers=headers, json=payload)
        assert response.status_code == 200 and response.json() == {"items": []}
        assert (
            client.post(f"{base}/{record_id}/resolve", headers=headers, json=payload).status_code
            == 409
        )
        with harness.factory() as session:
            row = session.get(MediaCleanupRow, record_id)
            assert row is not None and row.reason == "MANUALLY_REVIEWED"
        assert harness.events == []
    finally:
        client.close()
        get_settings.cache_clear()


def test_worker_retries_errors_off_event_loop_and_stops_cleanly(
    harness: RecoveryHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    import job_apply_pro.services.media_cleanup as module

    monkeypatch.setattr(module, "RECOVERY_INTERVAL_SECONDS", 0.001)
    calls: list[int] = []

    async def exercise() -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        service = harness.service()

        def recover() -> None:
            import threading

            calls.append(threading.get_ident())
            if len(calls) == 1:
                raise RuntimeError("synthetic transient failure")
            loop.call_soon_threadsafe(stop.set)

        monkeypatch.setattr(service, "recover", recover)
        await asyncio.wait_for(run_media_cleanup_worker(lambda: service, stop), timeout=5)
        import threading

        assert all(thread_id != threading.get_ident() for thread_id in calls)

    asyncio.run(exercise())
    assert len(calls) == 2
