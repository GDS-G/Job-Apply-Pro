from typing import Protocol

from job_apply_pro.domain.applications import Application, ApplicationCreate
from job_apply_pro.domain.candidate import CandidateBackup
from job_apply_pro.domain.checkpoints import EncryptedCheckpointRecord
from job_apply_pro.domain.jobs import Job, JobCreate
from job_apply_pro.domain.workbench import WorkflowRunSnapshot
from job_apply_pro.domain.workflow import TransitionCommand


class CandidateRepositoryProtocol(Protocol):
    def add_encrypted(self, backup: CandidateBackup) -> CandidateBackup: ...

    def get_encrypted(self, profile_id: str) -> CandidateBackup | None: ...


class JobRepositoryProtocol(Protocol):
    def add(self, command: JobCreate) -> Job: ...

    def get(self, job_id: str) -> Job | None: ...


class ApplicationRepositoryProtocol(Protocol):
    def add(self, command: ApplicationCreate) -> Application: ...

    def get(self, application_id: str) -> Application | None: ...


class CheckpointRepositoryProtocol(Protocol):
    def add_encrypted(self, checkpoint: EncryptedCheckpointRecord) -> EncryptedCheckpointRecord: ...

    def latest_encrypted(self, workflow_id: str) -> EncryptedCheckpointRecord | None: ...

    def next_sequence(self, workflow_id: str) -> int: ...


class WorkbenchRepositoryProtocol(Protocol):
    def get_snapshot(self, workflow_id: str) -> WorkflowRunSnapshot | None: ...

    def list_snapshots(self) -> list[WorkflowRunSnapshot]: ...

    def apply_transition(
        self, workflow_id: str, command: TransitionCommand
    ) -> WorkflowRunSnapshot: ...
