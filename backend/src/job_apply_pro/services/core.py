from uuid import uuid4

from job_apply_pro.domain.applications import Application, ApplicationCreate
from job_apply_pro.domain.candidate import (
    CandidateBackup,
    CandidateProfile,
    CandidateProfileCreate,
    CandidateStatus,
    ContactDetails,
)
from job_apply_pro.domain.checkpoints import (
    CheckpointCreate,
    EncryptedCheckpointRecord,
    WorkflowCheckpoint,
)
from job_apply_pro.domain.jobs import Job, JobCreate
from job_apply_pro.domain.workflow import utc_now
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.storage.repository_contracts import (
    ApplicationRepositoryProtocol,
    CandidateRepositoryProtocol,
    CheckpointRepositoryProtocol,
    JobRepositoryProtocol,
)


class RecordNotFoundError(LookupError):
    pass


class CoreService:
    def __init__(
        self,
        candidates: CandidateRepositoryProtocol,
        jobs: JobRepositoryProtocol,
        applications: ApplicationRepositoryProtocol,
        checkpoints: CheckpointRepositoryProtocol,
        cipher: SensitiveDataCipher,
    ) -> None:
        self._candidates = candidates
        self._jobs = jobs
        self._applications = applications
        self._checkpoints = checkpoints
        self._cipher = cipher

    def create_candidate(self, command: CandidateProfileCreate) -> CandidateProfile:
        profile_id = str(uuid4())
        now = utc_now()
        backup = CandidateBackup(
            profile_id=profile_id,
            display_name=command.display_name,
            encrypted_contact=self._cipher.encrypt_json(
                command.contact.model_dump(mode="json"), context=f"candidate:{profile_id}:contact"
            ),
            status=CandidateStatus.DRAFT,
            created_at=now,
            updated_at=now,
        )
        self._candidates.add_encrypted(backup)
        return self._candidate_from_backup(backup)

    def get_candidate(self, profile_id: str) -> CandidateProfile:
        backup = self._candidates.get_encrypted(profile_id)
        if backup is None:
            raise RecordNotFoundError(f"Candidate profile {profile_id} was not found")
        return self._candidate_from_backup(backup)

    def export_candidate(self, profile_id: str) -> CandidateBackup:
        backup = self._candidates.get_encrypted(profile_id)
        if backup is None:
            raise RecordNotFoundError(f"Candidate profile {profile_id} was not found")
        self._cipher.validate_envelope(
            backup.encrypted_contact, context=f"candidate:{profile_id}:contact"
        )
        return backup

    def restore_candidate(self, backup: CandidateBackup) -> CandidateProfile:
        self._cipher.validate_envelope(
            backup.encrypted_contact, context=f"candidate:{backup.profile_id}:contact"
        )
        self._candidates.add_encrypted(backup)
        return self._candidate_from_backup(backup)

    def create_job(self, command: JobCreate) -> Job:
        return self._jobs.add(command)

    def get_job(self, job_id: str) -> Job:
        job = self._jobs.get(job_id)
        if job is None:
            raise RecordNotFoundError(f"Job {job_id} was not found")
        return job

    def create_application(self, command: ApplicationCreate) -> Application:
        if self._candidates.get_encrypted(command.profile_id) is None:
            raise RecordNotFoundError(f"Candidate profile {command.profile_id} was not found")
        if self._jobs.get(command.job_id) is None:
            raise RecordNotFoundError(f"Job {command.job_id} was not found")
        return self._applications.add(command)

    def get_application(self, application_id: str) -> Application:
        application = self._applications.get(application_id)
        if application is None:
            raise RecordNotFoundError(f"Application {application_id} was not found")
        return application

    def save_checkpoint(self, workflow_id: str, command: CheckpointCreate) -> WorkflowCheckpoint:
        sequence = self._checkpoints.next_sequence(workflow_id)
        checkpoint = EncryptedCheckpointRecord(
            id=str(uuid4()),
            workflow_id=workflow_id,
            sequence=sequence,
            state=command.state,
            page_fingerprint=command.page_fingerprint,
            encrypted_payload=self._cipher.encrypt_json(
                command.payload, context=f"checkpoint:{workflow_id}:{sequence}"
            ),
            created_at=utc_now(),
        )
        self._checkpoints.add_encrypted(checkpoint)
        return self._decrypt_checkpoint(checkpoint)

    def latest_checkpoint(self, workflow_id: str) -> WorkflowCheckpoint:
        checkpoint = self._checkpoints.latest_encrypted(workflow_id)
        if checkpoint is None:
            raise RecordNotFoundError(f"Workflow {workflow_id} has no checkpoint")
        return self._decrypt_checkpoint(checkpoint)

    def _candidate_from_backup(self, backup: CandidateBackup) -> CandidateProfile:
        contact = ContactDetails.model_validate(
            self._cipher.decrypt_json(
                backup.encrypted_contact,
                context=f"candidate:{backup.profile_id}:contact",
            )
        )
        return CandidateProfile(
            id=backup.profile_id,
            display_name=backup.display_name,
            contact=contact,
            status=backup.status,
            created_at=backup.created_at,
            updated_at=backup.updated_at,
        )

    def _decrypt_checkpoint(self, checkpoint: EncryptedCheckpointRecord) -> WorkflowCheckpoint:
        return WorkflowCheckpoint(
            id=checkpoint.id,
            workflow_id=checkpoint.workflow_id,
            sequence=checkpoint.sequence,
            state=checkpoint.state,
            page_fingerprint=checkpoint.page_fingerprint,
            payload=self._cipher.decrypt_json(
                checkpoint.encrypted_payload,
                context=f"checkpoint:{checkpoint.workflow_id}:{checkpoint.sequence}",
            ),
            created_at=checkpoint.created_at,
        )
