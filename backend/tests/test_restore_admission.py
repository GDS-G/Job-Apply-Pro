"""Real process-interruption evidence, not a hardware/power-loss guarantee."""

import base64
import hashlib
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from job_apply_pro.config import Settings
from job_apply_pro.domain.operations import BackupCreate, BackupManifest, RestoreCreate, RestorePlan
from job_apply_pro.restore_admission import assert_runtime_admission, runtime_access
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.security.keys import StaticKeyProvider
from job_apply_pro.services.backup import BackupService
from job_apply_pro.services.restore_recovery import (
    MAX_RESTORE_FILES,
    Intent,
    Receipt,
    RestoreRecoveryService,
    Target,
)
from job_apply_pro.storage.database import Base
from job_apply_pro.storage.operations_repository import OperationsRepository
from job_apply_pro.storage.restore_gate_repository import (
    RestoreAdmissionError,
    RestoreGateRepository,
    checked_path,
    safe_relative,
    workspace_access,
)

SOURCE = Path(__file__).parents[1] / "src"
PROJECT = Path(__file__).parents[2]
KEY = base64.urlsafe_b64encode(b"t" * 32).decode("ascii")


def environment(root: Path) -> dict[str, str]:
    return {
        **{key: value for key, value in os.environ.items() if not key.startswith("JAP_")},
        "PYTHONPATH": str(SOURCE),
        "JAP_WORKSPACE_ROOT": str(root),
        "JAP_DATABASE_URL": f"sqlite:///{(root / 'app.db').as_posix()}",
        "JAP_DOCUMENT_DATA_DIR": str(root / "documents"),
        "JAP_BACKUP_DATA_DIR": str(root / "backups"),
        "JAP_RESTORE_STAGING_DIR": str(root / "restore-staging"),
        "JAP_BROWSER_DATA_DIR": str(root / "browser"),
        "JAP_BROWSER_ARTIFACT_DIR": str(root / "browser-artifacts"),
        "JAP_MASTER_KEY": KEY,
    }


def run(root: Path, *arguments: str, key: str | None = KEY) -> subprocess.CompletedProcess[str]:
    configured = environment(root)
    if key is None:
        configured.pop("JAP_MASTER_KEY")
    else:
        configured["JAP_MASTER_KEY"] = key
    return subprocess.run(
        [sys.executable, *arguments],
        env=configured,
        cwd=PROJECT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def cli(root: Path, *arguments: str, key: str | None = KEY) -> subprocess.CompletedProcess[str]:
    return run(root, "-m", "job_apply_pro.desktop_entry", *arguments, key=key)


@dataclass(frozen=True)
class Workspace:
    root: Path
    plan: RestorePlan
    manifest: BackupManifest
    cipher: SensitiveDataCipher

    @property
    def database(self) -> Path:
        return self.root / "app.db"

    @property
    def gate(self) -> RestoreGateRepository:
        return RestoreGateRepository(self.root)

    def prepare(
        self, *, plan: RestorePlan | None = None, manifest: BackupManifest | None = None
    ) -> Intent:
        return RestoreRecoveryService(self.root, self.cipher).prepare(
            plan or self.plan,
            manifest or self.manifest,
            database=self.database,
            documents=self.root / "documents",
            staging=self.root / "restore-staging",
            backups=self.root / "backups",
        )


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    database_url = f"sqlite:///{(tmp_path / 'app.db').as_posix()}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "resume.enc").write_bytes(b"reviewed-document")
    (documents / "letter.enc").write_bytes(b"reviewed-letter")
    cipher = SensitiveDataCipher(StaticKeyProvider(b"t" * 32, key_id="local-v1"))
    with Session(engine) as session:
        service = BackupService(
            OperationsRepository(session),
            cipher,
            database_url=database_url,
            document_dir=documents,
            backup_dir=tmp_path / "backups",
            staging_dir=tmp_path / "restore-staging",
        )
        manifest = service.create(BackupCreate(label="Synthetic recovery drill"))
        plan = service.stage_restore(manifest.id, RestoreCreate(categories=manifest.categories))
    engine.dispose()
    (documents / "resume.enc").write_bytes(b"current-document")
    (documents / "unrelated.enc").write_bytes(b"unrelated-document")
    return Workspace(tmp_path, plan, manifest, cipher)


def crash(workspace: Workspace, boundary: str) -> None:
    # Test-owned code replaces methods only in this synthetic subprocess.
    # The application has no production crash environment flag or bypass.
    source = f"""
import os
from job_apply_pro.desktop_entry import restore
from job_apply_pro.services.restore_recovery import RestoreRecoveryService
from job_apply_pro.storage.restore_gate_repository import RestoreGateRepository
from job_apply_pro.storage.operations_repository import OperationsRepository
boundary = {boundary!r}
if boundary == 'guard':
    original = RestoreGateRepository.begin
    def fail(self, *args, **kwargs):
        original(self, *args, **kwargs)
        os._exit(77)
    RestoreGateRepository.begin = fail
elif boundary == 'first-file':
    original = RestoreRecoveryService._replace
    def fail(self, *args, **kwargs):
        original(self, *args, **kwargs)
        os._exit(77)
    RestoreRecoveryService._replace = fail
elif boundary in ('before-commit', 'after-commit'):
    original = OperationsRepository.save_restore_result
    def fail(self, *args, **kwargs):
        if boundary == 'after-commit':
            original(self, *args, **kwargs)
            self.close_for_offline_restore()
        os._exit(77)
    OperationsRepository.save_restore_result = fail
elif boundary == 'receipt':
    RestoreRecoveryService.finalize = lambda *args: os._exit(77)
elif boundary == 'clear':
    original = RestoreGateRepository.finish_verified
    def fail(self, *args, **kwargs):
        original(self, *args, **kwargs)
        os._exit(77)
    RestoreGateRepository.finish_verified = fail
restore({workspace.plan.id!r}, {workspace.plan.fingerprint!r})
"""
    result = run(workspace.root, "-c", source)
    assert result.returncode == 77, result.stderr


@pytest.mark.parametrize("boundary", ["guard", "first-file", "before-commit", "after-commit"])
def test_crash_before_receipt_blocks_relaunch_without_database_reads(
    workspace: Workspace, boundary: str
) -> None:
    crash(workspace, boundary)
    assert workspace.gate.blocked()
    before = workspace.database.read_bytes()
    status = cli(workspace.root, "restore-status", key=None)
    assert status.returncode == 3
    assert status.stdout.strip() == '{"restore_recovery_required": true}'
    assert "resume" not in status.stdout
    for command in ("migrate", "serve"):
        result = cli(workspace.root, command, key=None)
        assert result.returncode == 3, result.stderr
        assert "Traceback" not in result.stderr
        assert workspace.database.read_bytes() == before
    finalized = cli(
        workspace.root, "restore-finalize", "--operation-id", workspace.gate.active_id()
    )
    assert finalized.returncode == 3
    assert workspace.gate.blocked()
    # The process's OS handle was released by termination; status/inspection
    # remains possible, but absence of a receipt never authorizes a clear.
    with workspace_access(workspace.root, restore=True):
        assert workspace.gate.blocked()


def test_committed_receipt_can_finalize_after_crash_and_preserves_unrelated_files(
    workspace: Workspace,
) -> None:
    crash(workspace, "receipt")
    operation_id = workspace.gate.active_id()
    operation = workspace.gate.operation_path(operation_id)
    assert b"resume" not in (operation / "intent.enc").read_bytes()
    assert b"resume" not in (operation / "receipt.enc").read_bytes()
    preimage = (operation / "database-preimage.enc").read_text("ascii")
    assert workspace.cipher.decrypt_bytes(
        preimage, context=f"restore:v1:{operation_id}:database-preimage"
    ).startswith(b"SQLite format 3")
    result = cli(workspace.root, "restore-finalize", "--operation-id", operation_id)
    assert result.returncode == 0, result.stderr
    assert not workspace.gate.blocked()
    assert (workspace.root / "documents" / "resume.enc").read_bytes() == b"reviewed-document"
    assert (workspace.root / "documents" / "unrelated.enc").read_bytes() == b"unrelated-document"
    assert (operation / "database-preimage.enc").exists()
    assert cli(workspace.root, "restore-status", key=None).returncode == 0


@pytest.mark.parametrize(
    "failure",
    [
        "missing-key",
        "wrong-key",
        "changed-target",
        "corrupt-receipt",
        "missing-receipt",
        "unknown-sidecar",
    ],
)
def test_recovery_uncertainty_never_clears_guard(workspace: Workspace, failure: str) -> None:
    crash(workspace, "receipt")
    operation_id = workspace.gate.active_id()
    key: str | None = KEY
    if failure == "missing-key":
        key = None
    elif failure == "wrong-key":
        key = base64.urlsafe_b64encode(b"x" * 32).decode("ascii")
    elif failure == "changed-target":
        (workspace.root / "documents" / "resume.enc").write_bytes(b"changed-again")
    elif failure == "corrupt-receipt":
        (workspace.gate.operation_path(operation_id) / "receipt.enc").write_text("broken")
    elif failure == "missing-receipt":
        (workspace.gate.operation_path(operation_id) / "receipt.enc").unlink()
    else:
        workspace.database.with_name("app.db-journal").write_bytes(b"unknown-journal")
    before = workspace.database.read_bytes()
    result = cli(workspace.root, "restore-finalize", "--operation-id", operation_id, key=key)
    assert result.returncode == 3
    assert "Traceback" not in result.stderr
    assert workspace.gate.blocked()
    assert workspace.database.read_bytes() == before
    if failure == "unknown-sidecar":
        assert workspace.database.with_name("app.db-journal").read_bytes() == b"unknown-journal"


def test_crash_after_verified_clear_is_admitted(workspace: Workspace) -> None:
    crash(workspace, "clear")
    assert not workspace.gate.blocked()
    assert cli(workspace.root, "restore-status", key=None).returncode == 0


@pytest.mark.parametrize(
    "entry",
    [
        "",
        "..",
        "../escape",
        "/absolute",
        "documents/a:stream",
        "documents/CON.txt",
        "documents/a.",
        "documents/a ",
        "documents\\escape",
        "documents//x",
    ],
)
def test_unsafe_platform_paths_are_rejected(entry: str) -> None:
    with pytest.raises(RestoreAdmissionError):
        safe_relative(entry)


@pytest.mark.parametrize(
    "mutation",
    [
        "staged-bytes",
        "extra-file",
        "missing-file",
        "archive-bytes",
        "manifest-and-stage",
        "external-stage",
    ],
)
def test_restore_rechecks_all_reviewed_inputs_before_guard_or_writes(
    workspace: Workspace, mutation: str, tmp_path: Path
) -> None:
    plan, manifest = workspace.plan, workspace.manifest
    source = Path(plan.staged_path) / "documents" / "resume.enc"
    before = workspace.database.read_bytes()
    if mutation == "staged-bytes":
        source.write_bytes(b"changed")
    elif mutation == "extra-file":
        source.with_name("extra.enc").write_bytes(b"new")
    elif mutation == "missing-file":
        source.unlink()
    elif mutation == "archive-bytes":
        Path(manifest.archive_path).write_bytes(b"changed")
    elif mutation == "manifest-and-stage":
        source.write_bytes(b"changed")
        entries = [
            entry.model_copy(
                update={"sha256": hashlib.sha256(b"changed").hexdigest(), "size_bytes": 7}
            )
            if entry.relative_path == "documents/resume.enc"
            else entry
            for entry in manifest.entries
        ]
        manifest = manifest.model_copy(update={"entries": entries})
    else:
        plan = plan.model_copy(update={"staged_path": str(tmp_path.parent)})
    with pytest.raises((RestoreAdmissionError, OSError, ValueError)):
        workspace.prepare(plan=plan, manifest=manifest)
    assert not workspace.gate.blocked()
    assert workspace.database.read_bytes() == before
    assert (workspace.root / "documents" / "resume.enc").read_bytes() == b"current-document"


def test_changed_staged_bytes_after_prepare_leave_durable_guard(workspace: Workspace) -> None:
    intent = workspace.prepare()
    source = Path(workspace.plan.staged_path) / "database" / "job_apply_pro.db"
    source.write_bytes(b"changed-after-prepare")
    before = workspace.database.read_bytes()
    with (
        workspace_access(workspace.root, restore=True),
        pytest.raises(RestoreAdmissionError, match="changed"),
    ):
        RestoreRecoveryService(workspace.root, workspace.cipher).apply(intent, lambda _plan: None)
    assert workspace.gate.blocked()
    assert workspace.database.read_bytes() == before


def test_key_free_gate_blocks_missing_database_creation_and_source_import(tmp_path: Path) -> None:
    gate = RestoreGateRepository(tmp_path)
    gate.control.mkdir()
    gate.guard.write_bytes(b"corrupt")
    for arguments in (
        ("-m", "job_apply_pro.desktop_entry", "migrate"),
        ("-c", "import job_apply_pro.main"),
        ("-c", "import job_apply_pro.storage.database"),
    ):
        result = run(tmp_path, *arguments, key=None)
        assert result.returncode != 0
        assert not (tmp_path / "app.db").exists()
        assert not (tmp_path / "documents").exists()


def test_explicit_workspace_guard_cannot_be_hidden_by_external_database(tmp_path: Path) -> None:
    gate = RestoreGateRepository(tmp_path)
    gate.control.mkdir()
    gate.guard.mkdir()
    settings = Settings(
        workspace_root=tmp_path,
        database_url=f"sqlite:///{(tmp_path.parent / 'external.db').as_posix()}",
    )
    with pytest.raises(RestoreAdmissionError):
        assert_runtime_admission(settings)


def test_runtime_restore_ownership_is_exclusive_and_reentrant_only_for_owner(
    tmp_path: Path,
) -> None:
    settings = Settings(
        workspace_root=tmp_path, database_url=f"sqlite:///{(tmp_path / 'app.db').as_posix()}"
    )
    with (
        runtime_access(settings),
        runtime_access(settings),
        pytest.raises(RestoreAdmissionError, match="busy"),
        workspace_access(tmp_path, restore=True),
    ):
        pytest.fail("Runtime ownership must prevent restore")
    with workspace_access(tmp_path, restore=True), workspace_access(tmp_path, restore=True):
        gate = RestoreGateRepository(tmp_path)
        gate.guard.write_text(str(uuid4()))
        with runtime_access(settings):
            pass
    with pytest.raises(RestoreAdmissionError), runtime_access(settings):
        pytest.fail("A later runtime has no restore capability")


def test_real_process_lock_blocks_competing_migration_then_releases_on_exit(tmp_path: Path) -> None:
    source = (
        "from pathlib import Path; import os,sys\n"
        "from job_apply_pro.storage.restore_gate_repository import workspace_access\n"
        "with workspace_access(Path(os.environ['JAP_WORKSPACE_ROOT']), restore=True):\n"
        " print('owned', flush=True)\n sys.stdin.read()"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", source],
        env=environment(tmp_path),
        cwd=PROJECT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(process.stdout.readline).result(timeout=15).strip() == "owned"
        result = cli(tmp_path, "migrate")
        assert result.returncode == 3
        assert not (tmp_path / "app.db").exists()
    finally:
        # Exact synthetic child only; never a process image-name kill.
        process.communicate(input="", timeout=15)
        assert process.returncode == 0
    with workspace_access(tmp_path, restore=True):
        pass


def test_hardlinked_inputs_are_not_exclusively_owned(workspace: Workspace) -> None:
    source = Path(workspace.plan.staged_path) / "documents" / "resume.enc"
    alias = workspace.root / "linked-copy"
    alias.hardlink_to(source)
    with pytest.raises(RestoreAdmissionError, match="exclusively owned"):
        workspace.prepare()


def test_junction_paths_fail_closed_without_relocating(tmp_path: Path) -> None:
    target = tmp_path / "actual"
    target.mkdir()
    link = tmp_path / "redirected"
    if sys.platform == "win32":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
    else:
        link.symlink_to(target, target_is_directory=True)
    with pytest.raises(RestoreAdmissionError, match=r"linked|redirected"):
        checked_path(link / "missing.db")


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_unknown_sidecars_are_preserved_before_any_target_write(
    workspace: Workspace, suffix: str
) -> None:
    intent = workspace.prepare()
    sidecar = workspace.database.with_name(workspace.database.name + suffix)
    sidecar.write_bytes(b"unknown-existing-sidecar")
    before = workspace.database.read_bytes()
    with (
        workspace_access(workspace.root, restore=True),
        pytest.raises(RestoreAdmissionError, match="sidecars"),
    ):
        RestoreRecoveryService(workspace.root, workspace.cipher).apply(intent, lambda _plan: None)
    assert not workspace.gate.blocked()
    assert workspace.database.read_bytes() == before
    assert sidecar.read_bytes() == b"unknown-existing-sidecar"


def test_existing_legacy_preimage_is_never_overwritten(workspace: Workspace) -> None:
    previous = workspace.database.with_suffix(".db.pre-restore")
    previous.write_bytes(b"unknown-previous-preimage")
    result = cli(
        workspace.root,
        "restore",
        "--plan-id",
        workspace.plan.id,
        "--fingerprint",
        workspace.plan.fingerprint,
    )
    assert result.returncode == 0, result.stderr
    assert previous.read_bytes() == b"unknown-previous-preimage"


def test_staged_journal_appearing_after_preparation_is_preserved_before_mail_inspection(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    intent = workspace.prepare()
    staged = Path(workspace.plan.staged_path) / "database" / "job_apply_pro.db"
    sidecar = staged.with_name(staged.name + "-journal")
    sidecar.write_bytes(b"unknown-staged-journal")
    before = workspace.database.read_bytes()

    def unexpected_mail_read(_current: Path, _staged: Path) -> None:
        pytest.fail("Mail preservation must not read an unclosed staged database")

    monkeypatch.setattr(BackupService, "_require_preserved_mail_attempts", unexpected_mail_read)
    with (
        workspace_access(workspace.root, restore=True),
        pytest.raises(RestoreAdmissionError, match="sidecars"),
    ):
        RestoreRecoveryService(workspace.root, workspace.cipher).apply(intent, lambda _plan: None)
    assert sidecar.read_bytes() == b"unknown-staged-journal"
    assert workspace.database.read_bytes() == before
    assert not workspace.gate.blocked()
    assert not (workspace.gate.control / "operations").exists()


def test_maximum_document_inventory_allows_its_additional_database_receipt(
    workspace: Workspace,
) -> None:
    documents = [
        Target(path=f"documents/{index}.enc", sha256="a" * 64, size=0)
        for index in range(MAX_RESTORE_FILES)
    ]
    payload = workspace.prepare().model_dump(mode="json")
    payload["inputs"] = [target.model_dump(mode="json") for target in documents]
    payload["plan"]["categories"] = ["DOCUMENTS"]
    payload["plan"]["file_count"] = MAX_RESTORE_FILES
    assert len(Intent.model_validate(payload).inputs) == MAX_RESTORE_FILES
    database = Target(path="app.db", sha256="b" * 64, size=1)
    targets = [*documents, database]
    assert len(Receipt(intent_sha256="c" * 64, targets=targets).targets) == MAX_RESTORE_FILES + 1
    with pytest.raises(ValidationError, match="at most 4097 items"):
        Receipt(intent_sha256="c" * 64, targets=[*targets, database])
    payload["inputs"].append(database.model_dump(mode="json"))
    with pytest.raises(ValidationError, match="at most 4096 items"):
        Intent.model_validate(payload)


@pytest.mark.parametrize("url", ["sqlite:///file:app.db?uri=true", "sqlite:///app.db?mode=ro"])
def test_ambiguous_sqlite_uri_overrides_fail_closed(url: str) -> None:
    with pytest.raises(RestoreAdmissionError):
        assert_runtime_admission(Settings(database_url=url, workspace_root=None))


def test_driver_qualified_sqlite_cannot_hide_guard(tmp_path: Path) -> None:
    gate = RestoreGateRepository(tmp_path)
    gate.control.mkdir()
    gate.guard.write_bytes(b"blocked")
    configured = environment(tmp_path)
    configured.pop("JAP_WORKSPACE_ROOT")
    configured["JAP_DATABASE_URL"] = f"sqlite+pysqlite:///{(tmp_path / 'app.db').as_posix()}"
    result = subprocess.run(
        [sys.executable, "-m", "job_apply_pro.desktop_entry", "migrate"],
        env=configured,
        cwd=PROJECT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 3
    assert not (tmp_path / "app.db").exists()


def test_restored_manifest_and_plan_roll_back_as_one_transaction(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        repository = OperationsRepository(session)

        def fail(_plan: RestorePlan) -> None:
            session.flush()
            raise RuntimeError("synthetic bookkeeping failure")

        monkeypatch.setattr(repository, "_put_restore_plan", fail)
        with pytest.raises(RuntimeError, match="synthetic"):
            repository.save_restore_result(workspace.manifest, workspace.plan)
        assert repository.get_backup(workspace.manifest.id) is None
        assert repository.get_restore_plan(workspace.plan.id) is None
    engine.dispose()
