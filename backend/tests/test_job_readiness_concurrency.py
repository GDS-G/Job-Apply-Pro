from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from job_apply_pro.domain.job_readiness import QualificationApproval, RequirementsApproval
from job_apply_pro.domain.knowledge import DocumentSelectionApproval
from job_apply_pro.services.job_readiness import JobReadinessService
from job_apply_pro.services.knowledge import CandidateKnowledgeService
from job_apply_pro.storage.database import Base
from job_apply_pro.storage.job_readiness_repository import JobReadinessRepository
from job_apply_pro.storage.knowledge_repository import CandidateKnowledgeRepository
from job_apply_pro.storage.models import (
    DocumentSelectionAuditRow,
    JobReadinessReviewRow,
    WorkflowEventRow,
)
from job_apply_pro.storage.repositories import (
    ApplicationRepository,
    CandidateRepository,
    JobRepository,
)
from test_job_readiness import Fixture


def test_identical_concurrent_approvals_share_one_real_transition_chain(tmp_path: Path) -> None:
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'concurrent.db').as_posix()}", connect_args={"timeout": 10}
    )
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            fixture = Fixture(session, tmp_path)
            requirements = fixture.requirements()
            # Exercise replay of the already reviewed first stage concurrently;
            # qualification and selection below are fresh concurrent approvals.
            qualification = fixture.qualification()

        def apply(
            command: RequirementsApproval | QualificationApproval | DocumentSelectionApproval,
            barrier: Barrier,
        ) -> str:
            with Session(engine) as session:
                knowledge = CandidateKnowledgeRepository(session)
                documents = CandidateKnowledgeService(
                    knowledge,
                    CandidateRepository(session),
                    JobRepository(session),
                    ApplicationRepository(session),
                    fixture.cipher,
                    document_data_dir=tmp_path / "documents",
                    document_max_bytes=1_000_000,
                )
                service = JobReadinessService(
                    JobReadinessRepository(session, fixture.cipher), knowledge, documents
                )
                barrier.wait(timeout=10)
                if isinstance(command, RequirementsApproval):
                    return service.approve_requirements(command).status
                if isinstance(command, QualificationApproval):
                    return service.approve_qualification(command).status
                return service.approve_resume(command).status

        for command in (requirements, qualification):
            barrier = Barrier(2)
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(apply, command, barrier) for _ in range(2)]
                results = [future.result() for future in futures]
            assert len(set(results)) == 1
        with Session(engine) as session:
            knowledge = CandidateKnowledgeRepository(session)
            documents = CandidateKnowledgeService(
                knowledge,
                CandidateRepository(session),
                JobRepository(session),
                ApplicationRepository(session),
                fixture.cipher,
                document_data_dir=tmp_path / "documents",
                document_max_bytes=1_000_000,
            )
            fixture.service = JobReadinessService(
                JobReadinessRepository(session, fixture.cipher), knowledge, documents
            )
            selection = fixture.selection()
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: apply(selection, barrier), range(2)))
        assert results == ["READY", "READY"]
        with Session(engine) as session:
            assert session.scalar(select(func.count(JobReadinessReviewRow.id))) == 3
            assert session.scalar(select(func.count(DocumentSelectionAuditRow.id))) == 1
            assert session.scalar(select(func.count(WorkflowEventRow.id))) == 4
    finally:
        engine.dispose()
