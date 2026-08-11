from typing import Protocol

from job_apply_pro.domain.applications import Application, ApplicationCreate
from job_apply_pro.domain.candidate import CandidateBackup
from job_apply_pro.domain.checkpoints import EncryptedCheckpointRecord
from job_apply_pro.domain.jobs import Job, JobCreate


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
