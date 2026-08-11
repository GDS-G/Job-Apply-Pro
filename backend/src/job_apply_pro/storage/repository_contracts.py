from typing import Protocol

from job_apply_pro.domain.ai import AICacheRecord, AIInvocationRecord
from job_apply_pro.domain.applications import (
    Application,
    ApplicationCreate,
    SubmittedDocumentEvidence,
)
from job_apply_pro.domain.browser import (
    BrowserActionResult,
    BrowserObservation,
    BrowserSessionRecord,
    BrowserSessionSnapshot,
    BrowserSessionState,
)
from job_apply_pro.domain.candidate import CandidateBackup
from job_apply_pro.domain.challenges import ChallengeEvent, ChallengeSessionSnapshot
from job_apply_pro.domain.checkpoints import EncryptedCheckpointRecord
from job_apply_pro.domain.communications import (
    CalendarMutationPlan,
    CommunicationRecord,
    FollowUp,
    MutationAudit,
    OutboundDraft,
)
from job_apply_pro.domain.jobs import Job, JobCreate, JobRequirement
from job_apply_pro.domain.knowledge import (
    AnswerLibraryRecord,
    CandidateClaim,
    CandidateDocument,
    CandidateDocumentVersion,
    CandidateDocumentVersionRecord,
    DocumentGenerationAudit,
    EvidenceSource,
    RetrievalChunkRecord,
)
from job_apply_pro.domain.portals import PortalRunSnapshot
from job_apply_pro.domain.workbench import WorkflowRunSnapshot
from job_apply_pro.domain.workflow import TransitionCommand


class CandidateRepositoryProtocol(Protocol):
    def add_encrypted(self, backup: CandidateBackup) -> CandidateBackup: ...

    def get_encrypted(self, profile_id: str) -> CandidateBackup | None: ...


class JobRepositoryProtocol(Protocol):
    def add(self, command: JobCreate) -> Job: ...

    def get(self, job_id: str) -> Job | None: ...

    def find_by_identity(self, source: str, external_id: str) -> Job | None: ...

    def list_requirements(self, job_id: str) -> list[JobRequirement]: ...


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


class BrowserRuntimeRepositoryProtocol(Protocol):
    def add(self, record: BrowserSessionRecord) -> BrowserSessionRecord: ...

    def get_record(self, session_id: str) -> BrowserSessionRecord | None: ...

    def list_snapshots(self, workflow_id: str | None = None) -> list[BrowserSessionSnapshot]: ...

    def save_observation(
        self,
        session_id: str,
        state: BrowserSessionState,
        observation: BrowserObservation,
        *,
        trace_path: str | None = None,
    ) -> BrowserSessionRecord: ...

    def set_state(
        self,
        session_id: str,
        state: BrowserSessionState,
        *,
        trace_path: str | None = None,
    ) -> BrowserSessionRecord: ...

    def add_action(self, result: BrowserActionResult) -> BrowserActionResult: ...

    def list_actions(self, session_id: str) -> list[BrowserActionResult]: ...

    def next_action_sequence(self, session_id: str) -> int: ...


class CandidateKnowledgeRepositoryProtocol(Protocol):
    def add_import_bundle(
        self,
        document: CandidateDocument,
        version: CandidateDocumentVersionRecord,
        evidence: EvidenceSource,
        claims: list[CandidateClaim],
    ) -> None: ...

    def add_generated_bundle(
        self,
        document: CandidateDocument,
        version: CandidateDocumentVersionRecord,
        evidence: EvidenceSource,
        audit: DocumentGenerationAudit,
    ) -> None: ...

    def list_documents(self, profile_id: str) -> list[CandidateDocument]: ...

    def get_document(self, document_id: str) -> CandidateDocument | None: ...

    def list_versions(self, document_id: str) -> list[CandidateDocumentVersion]: ...

    def get_version_record(self, version_id: str) -> CandidateDocumentVersionRecord | None: ...

    def list_claims(self, profile_id: str) -> list[CandidateClaim]: ...

    def get_claim(self, claim_id: str) -> CandidateClaim | None: ...

    def save_claim(self, claim: CandidateClaim) -> CandidateClaim: ...

    def add_answer(self, answer: AnswerLibraryRecord) -> AnswerLibraryRecord: ...

    def list_answers(self, profile_id: str) -> list[AnswerLibraryRecord]: ...

    def upsert_chunk(self, chunk: RetrievalChunkRecord) -> RetrievalChunkRecord: ...

    def delete_chunk(self, source_type: str, source_id: str) -> None: ...

    def list_chunks(self, profile_id: str) -> list[RetrievalChunkRecord]: ...

    def add_generation_audit(self, audit: DocumentGenerationAudit) -> DocumentGenerationAudit: ...

    def list_generation_audits(self, application_id: str) -> list[DocumentGenerationAudit]: ...

    def add_submitted_document(
        self, evidence: SubmittedDocumentEvidence
    ) -> SubmittedDocumentEvidence: ...

    def list_submitted_documents(self, application_id: str) -> list[SubmittedDocumentEvidence]: ...


class AIGatewayRepositoryProtocol(Protocol):
    def add_invocation(self, invocation: AIInvocationRecord) -> AIInvocationRecord: ...

    def get_cache(self, key: str) -> AICacheRecord | None: ...

    def upsert_cache(self, record: AICacheRecord) -> AICacheRecord: ...


class PortalRunRepositoryProtocol(Protocol):
    def save(self, run: PortalRunSnapshot) -> PortalRunSnapshot: ...

    def get(self, run_id: str) -> PortalRunSnapshot | None: ...

    def list_runs(self) -> list[PortalRunSnapshot]: ...

    def add_job_analysis(
        self,
        *,
        job_id: str,
        profile_id: str,
        requirements: list[str],
        score: float,
        explanation: dict[str, object],
    ) -> None: ...


class ChallengeRepositoryProtocol(Protocol):
    def save(self, snapshot: ChallengeSessionSnapshot) -> ChallengeSessionSnapshot: ...

    def get(self, session_id: str) -> ChallengeSessionSnapshot | None: ...

    def list_sessions(self, workflow_id: str | None = None) -> list[ChallengeSessionSnapshot]: ...

    def add_event(self, event: ChallengeEvent) -> ChallengeEvent: ...

    def list_events(self, session_id: str) -> list[ChallengeEvent]: ...

    def next_event_sequence(self, session_id: str) -> int: ...


class CommunicationRepositoryProtocol(Protocol):
    def save_record(self, record: CommunicationRecord) -> CommunicationRecord: ...

    def get_record(self, record_id: str) -> CommunicationRecord | None: ...

    def list_records(self) -> list[CommunicationRecord]: ...

    def save_draft(self, draft: OutboundDraft) -> OutboundDraft: ...

    def get_draft(self, draft_id: str) -> OutboundDraft | None: ...

    def list_drafts(self) -> list[OutboundDraft]: ...

    def save_calendar_plan(self, plan: CalendarMutationPlan) -> CalendarMutationPlan: ...

    def get_calendar_plan(self, plan_id: str) -> CalendarMutationPlan | None: ...

    def add_audit(self, audit: MutationAudit) -> MutationAudit: ...

    def find_audit_by_idempotency(self, key: str) -> MutationAudit | None: ...

    def list_audits(self) -> list[MutationAudit]: ...

    def save_follow_up(self, follow_up: FollowUp) -> FollowUp: ...

    def list_follow_ups(self) -> list[FollowUp]: ...
