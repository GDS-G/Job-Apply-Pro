from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session, sessionmaker

from job_apply_pro.config import get_settings
from job_apply_pro.domain.media_cleanup import MediaCleanupRecord, MediaCleanupState
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.security.keys import StaticKeyProvider
from job_apply_pro.storage.database import Base
from job_apply_pro.storage.media_cleanup_repository import (
    MediaCleanupConflict,
    MediaCleanupRepository,
)
from job_apply_pro.storage.models import MediaCleanupRow

_NOW = datetime(2026, 8, 14, 12, tzinfo=UTC)
_LEASE = timedelta(minutes=20)
_ACCOUNT = "a" * 64
_RESOURCE = "files/synthetic-recovery-image"


@pytest.fixture
def media_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'media-cleanup.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _repository(factory: sessionmaker[Session]) -> MediaCleanupRepository:
    return MediaCleanupRepository(factory, SensitiveDataCipher(StaticKeyProvider(b"a" * 32)))


def _create(
    repository: MediaCleanupRepository,
    *,
    owner: str = "invocation-owner",
    provider: str = "gemini",
    account: str = _ACCOUNT,
    now: datetime = _NOW,
) -> MediaCleanupRecord:
    return repository.create(provider, account, owner, now, now + _LEASE)


def _known(
    repository: MediaCleanupRepository, *, owner: str = "invocation-owner"
) -> MediaCleanupRecord:
    record = _create(repository, owner=owner)
    return repository.register_resource(record.id, owner, _RESOURCE, _NOW, _NOW + _LEASE)


def test_intent_is_committed_independently_before_any_remote_resource(
    media_factory: sessionmaker[Session],
) -> None:
    repository = _repository(media_factory)
    record = _create(repository)
    with media_factory() as session:
        stored = session.get(MediaCleanupRow, record.id)
        assert stored is not None
        assert stored.state == "UPLOADING"
        assert stored.encrypted_resource is None
    assert record.state is MediaCleanupState.UPLOADING
    assert not record.known_resource
    assert repository.list_recovery_candidates(_NOW) == []


def test_known_resource_is_encrypted_and_status_never_decrypts_or_discloses_it(
    media_factory: sessionmaker[Session],
) -> None:
    repository = _repository(media_factory)
    record = _known(repository)
    with media_factory() as session:
        row = session.get(MediaCleanupRow, record.id)
        assert row is not None
        assert row.encrypted_resource is not None
        assert row.encrypted_resource.startswith("jap:v1:")
        assert _RESOURCE not in row.encrypted_resource
    public = repository.list_public()[0]
    serialized = public.model_dump_json()
    assert public.known_resource
    assert _RESOURCE not in serialized
    assert _ACCOUNT not in serialized
    assert "invocation-owner" not in serialized
    assert "resource_name" not in serialized
    assert record.resource_name == _RESOURCE
    candidates = repository.list_recovery_candidates(_NOW + _LEASE)
    assert len(candidates) == 1 and candidates[0].resource_name is None
    assert candidates[0].known_resource


def test_restart_recovers_known_resource_only_after_lease_expiry(
    media_factory: sessionmaker[Session],
) -> None:
    original = _repository(media_factory)
    record = _known(original)
    recovered = _repository(media_factory)
    assert recovered.claim_recovery(record.id, "worker", _NOW, _NOW + _LEASE) is None
    resumed_at = _NOW + _LEASE
    claim = recovered.claim_recovery(record.id, "worker", resumed_at, resumed_at + _LEASE)
    assert claim is not None and claim.resource_name == _RESOURCE
    assert claim.state is MediaCleanupState.DELETE_PENDING
    assert claim.owner_token == "worker"
    assert (
        recovered.claim_recovery(record.id, "other-worker", resumed_at, resumed_at + _LEASE) is None
    )
    deleted = recovered.mark_deleted(record.id, "worker", resumed_at)
    assert deleted.state is MediaCleanupState.DELETED
    assert deleted.reason == "DELETION_CONFIRMED"
    assert not deleted.known_resource
    assert recovered.list_public() == []
    with media_factory() as session:
        row = session.get(MediaCleanupRow, record.id)
        assert row is not None and row.encrypted_resource is None


def test_unknown_finalization_becomes_manual_review_and_cannot_be_deleted(
    media_factory: sessionmaker[Session],
) -> None:
    repository = _repository(media_factory)
    record = _create(repository)
    resumed_at = _NOW + _LEASE
    claim = repository.claim_recovery(record.id, "worker", resumed_at, resumed_at + _LEASE)
    assert claim is not None
    assert claim.state is MediaCleanupState.MANUAL_REVIEW
    assert claim.reason == "UNKNOWN_UPLOAD"
    assert claim.resource_name is None and not claim.known_resource
    assert repository.list_recovery_candidates(resumed_at) == []
    with pytest.raises(MediaCleanupConflict):
        repository.mark_deleted(record.id, "worker", resumed_at)
    with pytest.raises(MediaCleanupConflict):
        _create(repository, now=resumed_at)
    with pytest.raises(MediaCleanupConflict):
        repository.resolve_manual(record.id, _NOW, resumed_at)
    closed = repository.resolve_manual(
        record.id, claim.updated_at, resumed_at + timedelta(seconds=1)
    )
    assert closed.reason == "MANUALLY_REVIEWED"
    assert closed.state is MediaCleanupState.DELETED
    assert _create(repository, now=resumed_at).state is MediaCleanupState.UPLOADING


def test_owner_can_create_multiple_active_images_but_other_owners_are_blocked(
    media_factory: sessionmaker[Session],
) -> None:
    repository = _repository(media_factory)
    first = _create(repository)
    second = _create(repository)
    assert first.id != second.id
    with pytest.raises(MediaCleanupConflict):
        _create(repository, owner="another-invocation")
    repository.relinquish(first.id, first.owner_token, _NOW)
    with pytest.raises(MediaCleanupConflict):
        _create(repository)


def test_configuration_alias_cannot_bypass_credential_admission(
    media_factory: sessionmaker[Session],
) -> None:
    repository = _repository(media_factory)
    original = _create(repository)
    different_account = _create(repository, owner="other", account="b" * 64)
    assert original.id != different_account.id
    with pytest.raises(MediaCleanupConflict):
        _create(repository, owner="other", provider="other-gemini")
    with pytest.raises(MediaCleanupConflict):
        _create(repository, owner="other")


def test_concurrent_admission_is_serialized_across_fresh_sqlite_sessions(
    media_factory: sessionmaker[Session],
) -> None:
    barrier = Barrier(2)

    def create(owner: str) -> str:
        repository = _repository(media_factory)
        barrier.wait(timeout=5)
        try:
            return _create(repository, owner=owner).id
        except MediaCleanupConflict:
            return "blocked"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(create, ["invocation-a", "invocation-b"]))
    assert outcomes.count("blocked") == 1
    with media_factory() as session:
        assert len(session.scalars(select(MediaCleanupRow)).all()) == 1


def test_wrong_or_expired_ownership_cannot_register_renew_relinquish_or_finish(
    media_factory: sessionmaker[Session],
) -> None:
    repository = _repository(media_factory)
    record = _create(repository)
    with pytest.raises(MediaCleanupConflict):
        repository.register_resource(record.id, "wrong", _RESOURCE, _NOW, _NOW + _LEASE)
    expired = _NOW + _LEASE
    with pytest.raises(MediaCleanupConflict):
        repository.register_resource(
            record.id, record.owner_token, _RESOURCE, expired, expired + _LEASE
        )
    with pytest.raises(MediaCleanupConflict):
        repository.renew(record.id, record.owner_token, expired, expired + _LEASE)
    with pytest.raises(MediaCleanupConflict):
        repository.relinquish(record.id, record.owner_token, expired)
    assert repository.list_public()[0].state is MediaCleanupState.UPLOADING


def test_renewal_keeps_active_resource_out_of_recovery(
    media_factory: sessionmaker[Session],
) -> None:
    repository = _repository(media_factory)
    record = _known(repository)
    renewal_time = _NOW + timedelta(minutes=10)
    renewed = repository.renew(record.id, record.owner_token, renewal_time, renewal_time + _LEASE)
    assert renewed.lease_until == renewal_time + _LEASE
    assert repository.list_recovery_candidates(_NOW + _LEASE) == []
    assert len(repository.list_recovery_candidates(renewal_time + _LEASE)) == 1


def test_normal_cleanup_relinquishes_then_claims_and_stale_owner_cannot_win(
    media_factory: sessionmaker[Session],
) -> None:
    repository = _repository(media_factory)
    record = _known(repository)
    pending = repository.relinquish(record.id, record.owner_token, _NOW)
    assert pending.state is MediaCleanupState.DELETE_PENDING
    assert pending.lease_until is None
    assert len(repository.list_recovery_candidates(_NOW)) == 1
    claim = repository.claim_recovery(record.id, "worker", _NOW, _NOW + _LEASE)
    assert claim is not None
    with pytest.raises(MediaCleanupConflict):
        repository.mark_deleted(record.id, record.owner_token, _NOW)
    with pytest.raises(MediaCleanupConflict):
        repository.mark_retry(record.id, record.owner_token, "DELETE_FAILED", _NOW, _NOW)
    with pytest.raises(MediaCleanupConflict):
        repository.register_resource(record.id, record.owner_token, _RESOURCE, _NOW, _NOW + _LEASE)
    repository.mark_deleted(record.id, "worker", _NOW)
    with pytest.raises(MediaCleanupConflict):
        repository.mark_retry(record.id, "worker", "DELETE_FAILED", _NOW, _NOW)


def test_retry_is_counted_and_not_claimable_until_due(
    media_factory: sessionmaker[Session],
) -> None:
    repository = _repository(media_factory)
    record = _known(repository)
    repository.relinquish(record.id, record.owner_token, _NOW)
    repository.claim_recovery(record.id, "worker", _NOW, _NOW + _LEASE)
    due = _NOW + timedelta(minutes=5)
    retry = repository.mark_retry(record.id, "worker", "DELETE_FAILED", _NOW, due)
    assert retry.attempts == 1 and retry.reason == "DELETE_FAILED"
    assert retry.next_attempt_at == due and retry.lease_until is None
    assert repository.list_recovery_candidates(_NOW) == []
    assert repository.claim_recovery(record.id, "worker-2", _NOW, _NOW + _LEASE) is None
    assert repository.claim_recovery(record.id, "worker-2", due, due + _LEASE) is not None


@pytest.mark.parametrize("changed_field", ["id", "provider_id", "account_fingerprint"])
def test_ciphertext_is_bound_to_record_provider_and_account(
    media_factory: sessionmaker[Session], changed_field: str
) -> None:
    repository = _repository(media_factory)
    record = _known(repository)
    with media_factory() as session:
        row = session.get(MediaCleanupRow, record.id)
        assert row is not None
        value = "b" * 64 if changed_field == "account_fingerprint" else "changed-identity"
        setattr(row, changed_field, value)
        session.commit()
    id = "changed-identity" if changed_field == "id" else record.id
    expired = _NOW + _LEASE
    # Listing remains useful without decrypting a corrupted row.
    assert repository.list_public()[0].known_resource
    assert repository.list_recovery_candidates(expired)[0].resource_name is None
    claim = repository.claim_recovery(id, "worker", expired, expired + _LEASE)
    assert claim is not None and claim.state is MediaCleanupState.MANUAL_REVIEW
    assert claim.reason == "UNREADABLE_RESOURCE"
    assert claim.known_resource and claim.resource_name is None
    with pytest.raises(MediaCleanupConflict):
        repository.resolve_manual(id, claim.updated_at, expired)


def test_unreadable_ciphertext_does_not_hide_other_candidates(
    media_factory: sessionmaker[Session],
) -> None:
    repository = _repository(media_factory)
    first = _known(repository)
    second = _known(repository)
    with media_factory() as session:
        row = session.get(MediaCleanupRow, first.id)
        assert row is not None
        row.encrypted_resource = "corrupt-envelope"
        session.commit()
    expired = _NOW + _LEASE
    candidates = repository.list_recovery_candidates(expired)
    assert len(candidates) == 2
    bad = repository.claim_recovery(first.id, "worker", expired, expired + _LEASE)
    good = repository.claim_recovery(second.id, "worker", expired, expired + _LEASE)
    assert bad is not None and bad.reason == "UNREADABLE_RESOURCE"
    assert good is not None and good.resource_name == _RESOURCE


@pytest.mark.parametrize(
    "name", ["../escape", "files/../escape", "files/UPPER", "https://evil.test/a"]
)
def test_invalid_remote_names_are_not_persisted(
    media_factory: sessionmaker[Session], name: str
) -> None:
    repository = _repository(media_factory)
    record = _create(repository)
    with pytest.raises(ValueError, match="resource name"):
        repository.register_resource(record.id, record.owner_token, name, _NOW, _NOW + _LEASE)
    assert not repository.list_public()[0].known_resource


def test_safe_reason_and_lease_validation(media_factory: sessionmaker[Session]) -> None:
    repository = _repository(media_factory)
    with pytest.raises(ValueError, match="future"):
        repository.create("gemini", _ACCOUNT, "owner", _NOW, _NOW)
    record = _known(repository)
    repository.relinquish(record.id, record.owner_token, _NOW)
    repository.claim_recovery(record.id, "worker", _NOW, _NOW + _LEASE)
    with pytest.raises(ValueError, match="safe internal code"):
        repository.mark_retry(record.id, "worker", "API key secret leaked", _NOW, _NOW)
    with pytest.raises(ValueError, match="past"):
        repository.mark_retry(
            record.id, "worker", "DELETE_FAILED", _NOW, _NOW - timedelta(seconds=1)
        )


def test_recovery_limit_is_bounded(media_factory: sessionmaker[Session]) -> None:
    repository = _repository(media_factory)
    _create(repository)
    _create(repository)
    assert len(repository.list_recovery_candidates(_NOW + _LEASE, limit=1)) == 1
    with pytest.raises(ValueError, match="limit"):
        repository.list_recovery_candidates(_NOW, limit=0)


def test_before_upload_abandonment_closes_intent_without_claiming_remote_deletion(
    media_factory: sessionmaker[Session],
) -> None:
    repository = _repository(media_factory)
    record = _create(repository)
    closed = repository.abandon_before_upload(record.id, record.owner_token, _NOW)
    assert closed.state is MediaCleanupState.DELETED
    assert closed.reason == "NOT_UPLOADED"
    assert not closed.known_resource
    assert closed.lease_until is None and closed.next_attempt_at is None
    assert repository.list_public() == []
    assert _create(repository, owner="fresh-invocation").state is MediaCleanupState.UPLOADING


def test_abandonment_requires_unknown_resource_and_current_owner(
    media_factory: sessionmaker[Session],
) -> None:
    repository = _repository(media_factory)
    record = _create(repository)
    with pytest.raises(MediaCleanupConflict):
        repository.abandon_before_upload(record.id, "wrong-owner", _NOW)
    with pytest.raises(MediaCleanupConflict):
        repository.abandon_before_upload(record.id, record.owner_token, _NOW + _LEASE)
    repository.register_resource(record.id, record.owner_token, _RESOURCE, _NOW, _NOW + _LEASE)
    with pytest.raises(MediaCleanupConflict):
        repository.abandon_before_upload(record.id, record.owner_token, _NOW)
    assert repository.list_public()[0].known_resource


def test_media_migration_round_trip_and_fresh_repository_persistence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'media-migration.db').as_posix()}"
    monkeypatch.setenv("JAP_DATABASE_URL", database_url)
    get_settings.cache_clear()
    try:
        config = Config("backend/alembic.ini")
        command.upgrade(config, "20260812_0022")
        command.upgrade(config, "20260814_0023")
        command.upgrade(config, "20260814_0023")
        engine = create_engine(database_url)
        inspector = inspect(engine)
        assert "ai_media_cleanup" in inspector.get_table_names()
        assert {index["name"] for index in inspector.get_indexes("ai_media_cleanup")} == {
            "ix_ai_media_cleanup_account",
            "ix_ai_media_cleanup_recovery",
        }
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        record = _known(_repository(factory))
        restarted = _repository(factory)
        expired = _NOW + _LEASE
        claim = restarted.claim_recovery(record.id, "worker", expired, expired + _LEASE)
        assert claim is not None and claim.resource_name == _RESOURCE
        engine.dispose()
        command.downgrade(config, "20260812_0022")
        command.upgrade(config, "20260814_0023")
        second_engine = create_engine(database_url)
        with second_engine.connect() as connection:
            assert connection.execute(select(MediaCleanupRow)).all() == []
        second_engine.dispose()
    finally:
        get_settings.cache_clear()


def test_account_filter_precedes_limit_and_never_decrypts_unmatched_resources(
    media_factory: sessionmaker[Session],
) -> None:
    repository = _repository(media_factory)
    old = _NOW - timedelta(days=1)
    with media_factory() as session:
        for index in range(101):
            session.add(
                MediaCleanupRow(
                    id=f"mismatched-resource-{index}",
                    provider_id="gemini",
                    account_fingerprint="b" * 64,
                    owner_token="old-owner",
                    state="IN_USE",
                    encrypted_resource="unreadable-mismatched-envelope",
                    attempts=0,
                    reason=None,
                    lease_until=old,
                    next_attempt_at=None,
                    created_at=old,
                    updated_at=old,
                )
            )
        session.commit()
    current = _known(repository)
    expired = _NOW + _LEASE
    assert current.id not in {record.id for record in repository.list_recovery_candidates(expired)}
    matching = repository.list_recovery_candidates(expired, accounts={_ACCOUNT})
    assert [record.id for record in matching] == [current.id]
    assert matching[0].known_resource and matching[0].resource_name is None
    assert repository.list_recovery_candidates(expired, accounts=set()) == []
    assert repository.list_recovery_candidates(expired, accounts={"c" * 64}) == []


def test_unknown_filter_recovers_intents_without_original_credentials(
    media_factory: sessionmaker[Session],
) -> None:
    repository = _repository(media_factory)
    unknown = _create(repository, account="b" * 64)
    known = _known(repository)
    expired = _NOW + _LEASE
    no_accounts = repository.list_recovery_candidates(expired, accounts=set(), include_unknown=True)
    assert [record.id for record in no_accounts] == [unknown.id]
    matching_and_unknown = repository.list_recovery_candidates(
        expired, accounts={_ACCOUNT}, include_unknown=True
    )
    assert {record.id for record in matching_and_unknown} == {unknown.id, known.id}
    claim = repository.claim_recovery(unknown.id, "worker", expired, expired + _LEASE)
    assert claim is not None and claim.state is MediaCleanupState.MANUAL_REVIEW
    assert repository.list_recovery_candidates(expired, accounts=set(), include_unknown=True) == []
