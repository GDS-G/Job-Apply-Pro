"""Real encrypted backup/restore regressions for retained external-history evidence.

All provider identities, credentials and calls in this module are synthetic. The
tests prove local restore admission and replay retention, not remote deduplication.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from job_apply_pro.domain.ai import AIInvocationRecord, AITaskType, DataClassification
from job_apply_pro.domain.communications import (
    CalendarEventSnapshot,
    CalendarMutationCreate,
    CalendarMutationPlan,
    IntegrationProvider,
    MutationAudit,
    MutationConfirmation,
    MutationStatus,
    OAuthTokenSet,
)
from job_apply_pro.domain.media_cleanup import MediaCleanupRecord, MediaCleanupState
from job_apply_pro.domain.operations import (
    BackupCategory,
    BackupCreate,
    BackupManifest,
    RestoreCreate,
    RestorePlan,
    RestoreStatus,
)
from job_apply_pro.integrations.communications import (
    FixtureCalendarProvider,
    ProviderMutationError,
)
from job_apply_pro.integrations.configuration import (
    CommunicationConfiguration,
    OAuthClientConfig,
    ProviderConnectionConfig,
)
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.security.keys import StaticKeyProvider
from job_apply_pro.services.backup import BackupService
from job_apply_pro.services.communications import CommunicationService
from job_apply_pro.services.restore_recovery import RestoreRecoveryService
from job_apply_pro.services.restore_rollback import RestoreRollback
from job_apply_pro.storage.ai_repository import AIGatewayRepository
from job_apply_pro.storage.communication_configuration_repository import (
    CommunicationConfigurationRepository,
)
from job_apply_pro.storage.communication_repository import CommunicationRepository
from job_apply_pro.storage.database import Base
from job_apply_pro.storage.media_cleanup_repository import MediaCleanupRepository
from job_apply_pro.storage.oauth_repository import OAuthAuthorizationSession, OAuthRepository
from job_apply_pro.storage.operations_repository import OperationsRepository
from job_apply_pro.storage.restore_gate_repository import workspace_access

_NOW = datetime(2026, 9, 14, 12, tzinfo=UTC)
_PROVIDER = IntegrationProvider.GOOGLE_CALENDAR
_REFERENCE = "oauth:google_calendar:synthetic-first-connection"
_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
_HISTORY_TABLES = (
    "calendar_mutation_plans",
    "communication_mutation_audits",
    "oauth_authorization_sessions",
    "oauth_credentials",
    "communication_configurations",
    "model_invocations",
    "ai_media_cleanup",
)


@dataclass(frozen=True)
class _HistoryRestore:
    root: Path
    cipher: SensitiveDataCipher

    @property
    def database(self) -> Path:
        return self.root / "job_apply_pro.db"

    @property
    def documents(self) -> Path:
        return self.root / "documents"

    @contextmanager
    def session(self) -> Iterator[Session]:
        engine = create_engine(f"sqlite:///{self.database.as_posix()}")
        try:
            with Session(engine) as session:
                yield session
        finally:
            engine.dispose()

    @contextmanager
    def media(self) -> Iterator[MediaCleanupRepository]:
        engine = create_engine(f"sqlite:///{self.database.as_posix()}")
        try:
            yield MediaCleanupRepository(sessionmaker(bind=engine), self.cipher)
        finally:
            engine.dispose()

    def backup_service(self, session: Session) -> BackupService:
        return BackupService(
            OperationsRepository(session),
            self.cipher,
            database_url=f"sqlite:///{self.database.as_posix()}",
            document_dir=self.documents,
            backup_dir=self.root / "backups",
            staging_dir=self.root / "staging",
        )

    def backup(self) -> BackupManifest:
        with self.session() as session:
            manifest = self.backup_service(session).create(
                BackupCreate(categories={BackupCategory.DATABASE, BackupCategory.DOCUMENTS})
            )
        encoded = Path(manifest.archive_path).read_bytes()
        assert encoded.startswith(b"jap:v1:")
        assert b"SQLite format 3" not in encoded
        assert b"synthetic-access-token" not in encoded
        assert self.cipher.decrypt_bytes(
            encoded.decode("ascii"), context=f"backup:{manifest.id}:archive"
        ).startswith(b"PK")
        return manifest

    def stage(self, manifest: BackupManifest) -> RestorePlan:
        with self.session() as session:
            return self.backup_service(session).stage_restore(
                manifest.id, RestoreCreate(categories=manifest.categories)
            )

    def assert_refused(
        self,
        manifest: BackupManifest,
        *,
        message: str = "lose or change recorded history",
    ) -> None:
        from job_apply_pro.services.restore_history import RestoreHistoryError

        plan = self.stage(manifest)
        original_database = self.database.read_bytes()
        staged = Path(plan.staged_path)
        original_staged = {
            path.relative_to(staged): path.read_bytes()
            for path in staged.rglob("*")
            if path.is_file()
        }
        original_documents = {
            path.relative_to(self.documents): path.read_bytes()
            for path in self.documents.rglob("*")
            if path.is_file()
        }
        original_archive = Path(manifest.archive_path).read_bytes()
        recovery = RestoreRecoveryService(self.root, self.cipher)
        with workspace_access(self.root, restore=True):
            intent = recovery.prepare(
                plan,
                manifest,
                database=self.database,
                documents=self.documents,
                staging=self.root / "staging",
                backups=self.root / "backups",
            )
            with pytest.raises(RestoreHistoryError, match=message) as error:
                recovery.apply(intent)
        assert str(error.value)
        for sensitive in (
            "synthetic-access-token",
            "synthetic-refresh-token",
            "synthetic-code-verifier",
            "synthetic-calendar-key",
            "synthetic-calendar-title",
            "candidate@example.test",
            _REFERENCE,
            str(self.root),
        ):
            assert sensitive not in str(error.value)
        assert self.database.read_bytes() == original_database
        assert {
            path.relative_to(staged): path.read_bytes()
            for path in staged.rglob("*")
            if path.is_file()
        } == original_staged
        assert {
            path.relative_to(self.documents): path.read_bytes()
            for path in self.documents.rglob("*")
            if path.is_file()
        } == original_documents
        assert Path(manifest.archive_path).read_bytes() == original_archive
        assert not recovery.gate.blocked()
        assert not (recovery.gate.control / "operations").exists()
        assert not self.database.with_suffix(".db.pre-restore").exists()
        assert not self.database.with_suffix(".db.restore.tmp").exists()

    def assert_applied(self, manifest: BackupManifest) -> None:
        plan = self.stage(manifest)
        original_database = self.database.read_bytes()
        with closing(sqlite3.connect(self.database)) as current:
            original_history = {
                table: current.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                for table in _HISTORY_TABLES
            }
        recovery = RestoreRecoveryService(self.root, self.cipher)

        with workspace_access(self.root, restore=True):
            intent = recovery.prepare(
                plan,
                manifest,
                database=self.database,
                documents=self.documents,
                staging=self.root / "staging",
                backups=self.root / "backups",
            )
            applied = recovery.apply(intent)
        assert applied.status is RestoreStatus.APPLIED
        assert not recovery.gate.blocked()
        operations = list((recovery.gate.control / "operations").iterdir())
        assert len(operations) == 1
        rollback = RestoreRollback(recovery)
        prepared = rollback._load(operations[0].name)
        database_target = prepared.targets[-1]
        assert database_target.path == "job_apply_pro.db"
        assert database_target.before is not None
        assert (
            rollback._read_image(prepared.operation_id, database_target.before) == original_database
        )
        receipt = rollback._receipt(prepared)
        assert receipt is not None and receipt.outcome == "APPLIED"
        if BackupCategory.DATABASE in manifest.categories:
            with closing(
                sqlite3.connect(Path(plan.staged_path) / "database/job_apply_pro.db")
            ) as staged:
                expected_history = {
                    table: staged.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                    for table in _HISTORY_TABLES
                }
        else:
            expected_history = original_history
        with closing(sqlite3.connect(self.database)) as current:
            for table in _HISTORY_TABLES:
                assert (
                    current.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                    == expected_history[table]
                )
            assert current.execute(
                "SELECT status FROM restore_plans WHERE id=?", (plan.id,)
            ).fetchone() == ("APPLIED",)


@pytest.fixture
def history(tmp_path: Path) -> _HistoryRestore:
    result = _HistoryRestore(tmp_path, SensitiveDataCipher(StaticKeyProvider(b"h" * 32)))
    engine = create_engine(f"sqlite:///{result.database.as_posix()}")
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()
    with closing(sqlite3.connect(result.database)) as connection, connection:
        connection.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        connection.execute("INSERT INTO alembic_version VALUES ('20260913_0027')")
    result.documents.mkdir()
    (result.documents / "synthetic-unreferenced.enc").write_text(
        result.cipher.encrypt_bytes(b"synthetic document", context="synthetic-test-document"),
        encoding="ascii",
    )
    return result


def _calendar_service(
    session: Session, history: _HistoryRestore, adapter: FixtureCalendarProvider
) -> CommunicationService:
    return CommunicationService(
        CommunicationRepository(session, history.cipher),
        calendar_adapters={adapter.provider: adapter},
    )


def _calendar_plan(
    service: CommunicationService, provider: IntegrationProvider, *, update: bool = False
) -> CalendarMutationPlan:
    event = CalendarEventSnapshot(
        provider_event_id="synthetic-calendar-provider-id",
        title="synthetic-calendar-title",
        start_at=_NOW + timedelta(days=1),
        end_at=_NOW + timedelta(days=1, hours=1),
        time_zone="UTC",
        attendees=["candidate@example.test"],
    )
    return service.plan_calendar_mutation(
        CalendarMutationCreate(
            provider=provider,
            event=event,
            prior_event=event.model_copy(update={"title": "Synthetic previous title"})
            if update
            else None,
        )
    )


def _confirmation(plan: CalendarMutationPlan) -> MutationConfirmation:
    return MutationConfirmation(
        fingerprint=plan.fingerprint,
        idempotency_key="synthetic-calendar-key",
        confirmed_by="synthetic-reviewer",
    )


@pytest.mark.parametrize("provider", [_PROVIDER, IntegrationProvider.OUTLOOK_CALENDAR])
@pytest.mark.parametrize("update", [False, True], ids=["create", "update"])
@pytest.mark.parametrize(
    "status", [MutationStatus.CONFIRMED, MutationStatus.FAILED, MutationStatus.PLANNED]
)
def test_backup_before_calendar_call_preserves_attempt_and_replay(
    history: _HistoryRestore,
    monkeypatch: pytest.MonkeyPatch,
    provider: IntegrationProvider,
    update: bool,
    status: MutationStatus,
) -> None:
    adapter = FixtureCalendarProvider(provider)
    calls = 0

    def rejected_call(event: CalendarEventSnapshot, *, idempotency_key: str) -> str:
        nonlocal calls
        calls += 1
        if status is MutationStatus.FAILED:
            raise ProviderMutationError("Synthetic provider failure")
        raise RuntimeError("Synthetic interruption after transmission")

    if status is not MutationStatus.CONFIRMED:
        monkeypatch.setattr(adapter, "update_event" if update else "create_event", rejected_call)
    with history.session() as session:
        service = _calendar_service(session, history, adapter)
        plan = _calendar_plan(service, provider, update=update)
    manifest = history.backup()
    with history.session() as session:
        service = _calendar_service(session, history, adapter)
        if status is MutationStatus.CONFIRMED:
            audit = service.execute_calendar_mutation(plan.id, _confirmation(plan))
        else:
            expected = ProviderMutationError if status is MutationStatus.FAILED else RuntimeError
            with pytest.raises(expected, match="Synthetic"):
                service.execute_calendar_mutation(plan.id, _confirmation(plan))
            audit = service.list_audits()[0]
        assert audit.status is status
    history.assert_refused(manifest)
    with history.session() as session:
        replay = _calendar_service(session, history, adapter).execute_calendar_mutation(
            plan.id, _confirmation(plan)
        )
        assert replay.id == audit.id
        assert replay.status is status
    assert calls == (0 if status is MutationStatus.CONFIRMED else 1)
    assert len(adapter.mutations) == (1 if status is MutationStatus.CONFIRMED else 0)


@pytest.mark.parametrize("status", [MutationStatus.ACCEPTED, MutationStatus.UNCERTAIN])
def test_calendar_audit_nonterminal_status_is_not_discardable(
    history: _HistoryRestore, status: MutationStatus
) -> None:
    adapter = FixtureCalendarProvider(_PROVIDER)
    with history.session() as session:
        plan = _calendar_plan(_calendar_service(session, history, adapter), _PROVIDER)
    manifest = history.backup()
    with history.session() as session:
        CommunicationRepository(session, history.cipher).add_audit(
            MutationAudit(
                id=str(uuid4()),
                kind=plan.kind,
                provider=plan.provider,
                resource_id=plan.id,
                idempotency_key="synthetic-calendar-key",
                fingerprint=plan.fingerprint,
                status=status,
                confirmed_by="synthetic-reviewer",
                occurred_at=_NOW,
            )
        )
    history.assert_refused(manifest)
    assert not adapter.mutations


def test_backup_before_calendar_plan_cannot_discard_reviewed_plan(history: _HistoryRestore) -> None:
    manifest = history.backup()
    adapter = FixtureCalendarProvider(_PROVIDER)
    with history.session() as session:
        _calendar_plan(_calendar_service(session, history, adapter), _PROVIDER)
    history.assert_refused(manifest)
    assert not adapter.mutations


def _authorization(state_hash: str = "a" * 64) -> OAuthAuthorizationSession:
    return OAuthAuthorizationSession(
        state_hash=state_hash,
        provider=_PROVIDER,
        client_id="synthetic-public-client",
        redirect_uri="http://127.0.0.1:8765/api/v1/communications/oauth/callback",
        requested_scopes=_SCOPES,
        code_verifier="synthetic-code-verifier",
        expires_at=_NOW + timedelta(minutes=10),
    )


def _tokens(*, refreshed: bool = False) -> OAuthTokenSet:
    return OAuthTokenSet(
        access_token=SecretStr(
            "synthetic-access-token-new" if refreshed else "synthetic-access-token"
        ),
        refresh_token=SecretStr(
            "synthetic-refresh-token-new" if refreshed else "synthetic-refresh-token"
        ),
        expires_at=_NOW + timedelta(hours=2 if refreshed else 1),
        granted_scopes=_SCOPES,
        account_hint="candidate@example.test",
        account_identity="synthetic-provider-account",
    )


@pytest.mark.parametrize("change", ["consumed", "replaced", "created"])
def test_backup_cannot_reopen_or_drop_oauth_authorization_state(
    history: _HistoryRestore, change: str
) -> None:
    if change != "created":
        with history.session() as session:
            OAuthRepository(session, history.cipher).save_authorization_session(_authorization())
    manifest = history.backup()
    with history.session() as session:
        repository = OAuthRepository(session, history.cipher)
        if change == "consumed":
            assert repository.consume_authorization_session("a" * 64, now=_NOW) is not None
        else:
            repository.save_authorization_session(_authorization("b" * 64))
    history.assert_refused(manifest)
    with history.session() as session:
        assert (
            OAuthRepository(session, history.cipher).consume_authorization_session(
                "a" * 64, now=_NOW + timedelta(seconds=1)
            )
            is None
        )


@pytest.mark.parametrize("change", ["refreshed", "replaced", "deleted", "created"])
def test_backup_cannot_roll_back_or_resurrect_oauth_credentials(
    history: _HistoryRestore, change: str
) -> None:
    if change != "created":
        with history.session() as session:
            OAuthRepository(session, history.cipher).save_tokens(
                _PROVIDER, _REFERENCE, _tokens(), now=_NOW
            )
    manifest = history.backup()
    with history.session() as session:
        repository = OAuthRepository(session, history.cipher)
        if change == "deleted":
            assert repository.delete_tokens(_PROVIDER)
        elif change == "refreshed":
            assert repository.refresh_tokens_if_current(
                _PROVIDER, _REFERENCE, _tokens(refreshed=True), now=_NOW + timedelta(minutes=1)
            )
        else:
            repository.save_tokens(
                _PROVIDER,
                "oauth:google_calendar:synthetic-new-connection",
                _tokens(refreshed=True),
                now=_NOW + timedelta(minutes=1),
            )
    history.assert_refused(manifest)
    with history.session() as session:
        current = OAuthRepository(session, history.cipher).load_tokens(_PROVIDER)
        if change == "deleted":
            assert current is None
        else:
            assert current is not None
            assert current[1].access_token == _tokens(refreshed=True).access_token


def _configuration(
    *, connected: bool = False, write_enabled: bool = False
) -> CommunicationConfiguration:
    return CommunicationConfiguration(
        providers=[
            ProviderConnectionConfig(
                provider=_PROVIDER,
                credential_reference=_REFERENCE if connected else None,
                account_hint="candidate@example.test" if connected else None,
                granted_scopes=_SCOPES if connected else [],
                write_enabled=write_enabled,
            )
        ],
        oauth_clients=[
            OAuthClientConfig(
                provider=_PROVIDER,
                client_id="synthetic-public-client",
                requested_scopes=_SCOPES,
            )
        ],
    )


@pytest.mark.parametrize("change", ["deleted", "changed", "created"])
def test_backup_cannot_restore_only_or_revert_provider_configuration(
    history: _HistoryRestore, change: str
) -> None:
    if change != "created":
        with history.session() as session:
            CommunicationConfigurationRepository(session, history.cipher).save(
                _configuration(write_enabled=True), now=_NOW
            )
    manifest = history.backup()
    with history.session() as session:
        repository = CommunicationConfigurationRepository(session, history.cipher)
        if change == "deleted":
            assert repository.delete()
        else:
            repository.save(_configuration(), now=_NOW + timedelta(minutes=1))
    history.assert_refused(manifest)


def _invocation(status: str = "SUCCEEDED") -> AIInvocationRecord:
    return AIInvocationRecord(
        id=str(uuid4()),
        task_type=AITaskType.ANSWER,
        provider_id="synthetic-model-provider",
        model_id="synthetic-model",
        prompt_version="1",
        schema_version="1",
        input_hash="a" * 64,
        cache_key="b" * 64,
        classification=DataClassification.ROUTINE,
        status=status,
        attempts=0 if status == "CACHED" else 1,
        route=["synthetic-model"],
        input_tokens=1,
        output_tokens=1,
        cost_micros=1,
        latency_ms=1,
        error_code="SYNTHETIC_FAILURE" if status == "FAILED" else None,
        created_at=_NOW,
        completed_at=_NOW + timedelta(seconds=1),
    )


@pytest.mark.parametrize("status", ["SUCCEEDED", "FAILED", "CACHED"])
def test_backup_preserves_each_model_invocation_not_only_cache_identity(
    history: _HistoryRestore, status: str
) -> None:
    first = _invocation()
    with history.session() as session:
        AIGatewayRepository(session).add_invocation(first)
    manifest = history.backup()
    second = _invocation(status)
    assert first.id != second.id
    assert first.cache_key == second.cache_key
    with history.session() as session:
        AIGatewayRepository(session).add_invocation(second)
    history.assert_refused(manifest)


def _media_intent(repository: MediaCleanupRepository) -> MediaCleanupRecord:
    return repository.create(
        "synthetic-media-provider",
        "c" * 64,
        "synthetic-owner",
        _NOW,
        _NOW + timedelta(minutes=1),
    )


def _close_media(
    repository: MediaCleanupRepository, record: MediaCleanupRecord, reason: str
) -> MediaCleanupRecord:
    if reason == "NOT_UPLOADED":
        return repository.abandon_before_upload(record.id, record.owner_token, _NOW)
    if reason == "MANUALLY_REVIEWED":
        manual = repository.relinquish(record.id, record.owner_token, _NOW)
        return repository.resolve_manual(record.id, manual.updated_at, _NOW + timedelta(seconds=1))
    repository.register_resource(
        record.id, record.owner_token, "files/synthetic-media", _NOW, _NOW + timedelta(minutes=1)
    )
    repository.relinquish(record.id, record.owner_token, _NOW)
    claimed = repository.claim_recovery(
        record.id, "synthetic-recovery-owner", _NOW, _NOW + timedelta(minutes=1)
    )
    assert claimed is not None
    return repository.mark_deleted(record.id, claimed.owner_token, _NOW + timedelta(seconds=1))


@pytest.mark.parametrize("reason", ["DELETION_CONFIRMED", "NOT_UPLOADED", "MANUALLY_REVIEWED"])
def test_backup_before_terminal_media_record_cannot_discard_cleanup_history(
    history: _HistoryRestore, reason: str
) -> None:
    manifest = history.backup()
    with history.media() as repository:
        record = _close_media(repository, _media_intent(repository), reason)
        assert record.state is MediaCleanupState.DELETED
        assert record.reason == reason
        assert record.resource_name is None
    history.assert_refused(manifest)


def test_backup_before_confirmed_media_deletion_cannot_resurrect_remote_ownership(
    history: _HistoryRestore,
) -> None:
    with history.media() as repository:
        record = _media_intent(repository)
        repository.register_resource(
            record.id,
            record.owner_token,
            "files/synthetic-media",
            _NOW,
            _NOW + timedelta(minutes=1),
        )
    manifest = history.backup()
    with history.media() as repository:
        repository.relinquish(record.id, record.owner_token, _NOW)
        claimed = repository.claim_recovery(
            record.id, "synthetic-recovery-owner", _NOW, _NOW + timedelta(minutes=1)
        )
        assert claimed is not None
        deleted = repository.mark_deleted(record.id, claimed.owner_token, _NOW)
        assert deleted.state is MediaCleanupState.DELETED
    history.assert_refused(manifest, message="unresolved current or staged provider media cleanup")


def test_real_encrypted_restore_without_protected_history_is_allowed(
    history: _HistoryRestore,
) -> None:
    history.assert_applied(history.backup())


def test_real_encrypted_restore_with_identical_cross_domain_history_is_allowed(
    history: _HistoryRestore,
) -> None:
    adapter = FixtureCalendarProvider(_PROVIDER)
    with history.session() as session:
        oauth = OAuthRepository(session, history.cipher)
        oauth.save_authorization_session(_authorization())
        assert oauth.consume_authorization_session("a" * 64, now=_NOW) is not None
        oauth.save_tokens(_PROVIDER, _REFERENCE, _tokens(), now=_NOW)
        CommunicationConfigurationRepository(session, history.cipher).save(
            _configuration(connected=True, write_enabled=True), now=_NOW
        )
        service = _calendar_service(session, history, adapter)
        plan = _calendar_plan(service, _PROVIDER)
        audit = service.execute_calendar_mutation(plan.id, _confirmation(plan))
        AIGatewayRepository(session).add_invocation(_invocation())
    with history.media() as repository:
        _close_media(repository, _media_intent(repository), "DELETION_CONFIRMED")
    history.assert_applied(history.backup())
    with history.session() as session:
        replay = _calendar_service(session, history, adapter).execute_calendar_mutation(
            plan.id, _confirmation(plan)
        )
        assert replay.id == audit.id
        assert replay.status is MutationStatus.CONFIRMED
        assert (
            OAuthRepository(session, history.cipher).consume_authorization_session(
                "a" * 64, now=_NOW + timedelta(seconds=1)
            )
            is None
        )
    assert len(adapter.mutations) == 1
