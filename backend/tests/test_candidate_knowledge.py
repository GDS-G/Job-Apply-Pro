from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from docx import Document as DocxDocument
from fastapi.testclient import TestClient
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy import select
from sqlalchemy.orm import Session

from job_apply_pro.api.routes.knowledge import get_knowledge_service
from job_apply_pro.documents.extractors import extract_document
from job_apply_pro.domain.candidate import CandidateProfileCreate, ContactDetails
from job_apply_pro.domain.knowledge import (
    AnswerLibraryCreate,
    ClaimPermittedUse,
    ClaimReview,
    ClaimVerificationStatus,
    DocumentKind,
    RetrievalQuery,
)
from job_apply_pro.main import app
from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.security.keys import StaticKeyProvider
from job_apply_pro.services.core import CoreService
from job_apply_pro.services.knowledge import (
    CandidateKnowledgeConflictError,
    CandidateKnowledgeService,
)
from job_apply_pro.storage.knowledge_repository import CandidateKnowledgeRepository
from job_apply_pro.storage.models import (
    AnswerLibraryRow,
    DocumentVersionRow,
    RetrievalChunkRow,
)
from job_apply_pro.storage.repositories import (
    ApplicationRepository,
    CandidateRepository,
    CheckpointRepository,
    JobRepository,
)


def _profile(session: Session) -> str:
    candidates = CandidateRepository(session)
    profile = CoreService(
        candidates,
        JobRepository(session),
        ApplicationRepository(session),
        CheckpointRepository(session),
        SensitiveDataCipher(StaticKeyProvider(b"k" * 32)),
    ).create_candidate(
        CandidateProfileCreate(
            display_name="Knowledge profile",
            contact=ContactDetails(
                full_name="Knowledge User",
                email="knowledge@example.com",
            ),
        )
    )
    return profile.id


def _service(session: Session, tmp_path: Path) -> CandidateKnowledgeService:
    return CandidateKnowledgeService(
        CandidateKnowledgeRepository(session),
        CandidateRepository(session),
        SensitiveDataCipher(StaticKeyProvider(b"k" * 32)),
        document_data_dir=tmp_path / "documents",
        document_max_bytes=1_000_000,
    )


RESUME = b"""Knowledge User
knowledge.user@example.com | (312) 555-0142
Senior Network Engineer | Jan 2020 - Mar 2023 | BGP automation
Network Engineer | Jan 2022 - Dec 2024 | BGP Python automation
Skills: Python, BGP, automation, Docker, SQL
Certification: CCNP
"""


def test_import_review_lock_experience_and_private_retrieval(
    session: Session, tmp_path: Path
) -> None:
    profile_id = _profile(session)
    service = _service(session, tmp_path)
    imported = service.import_document(
        profile_id,
        file_name="network-resume.txt",
        data=RESUME,
        kind=DocumentKind.RESUME,
        display_name="Network resume",
        variant_label="Network engineering",
        job_family_tags=["network", "infrastructure", "network"],
        is_primary=True,
    )

    assert imported.document.variant_label == "Network engineering"
    assert imported.document.job_family_tags == ["infrastructure", "network"]
    assert imported.extraction.character_count > 100
    assert all(
        claim.verification_status is ClaimVerificationStatus.PROPOSED
        for claim in imported.proposed_claims
    )
    stored_version = session.scalar(
        select(DocumentVersionRow).where(DocumentVersionRow.id == imported.version.id)
    )
    assert stored_version is not None
    assert "knowledge.user@example.com" not in stored_version.encrypted_extraction
    assert "knowledge.user@example.com" not in Path(stored_version.storage_path).read_text()
    assert service.get_extraction(imported.version.id) == imported.extraction

    bgp_skill = next(
        claim for claim in imported.proposed_claims if claim.canonical_key == "skill.bgp"
    )
    verified_skill = service.review_claim(
        bgp_skill.id,
        ClaimReview(
            approved=True,
            permitted_use=ClaimPermittedUse.APPLICATIONS,
        ),
    )
    assert verified_skill.locked
    experience_claims = [
        claim
        for claim in imported.proposed_claims
        if claim.canonical_key.startswith("experience.bgp.")
    ]
    for claim in experience_claims:
        service.review_claim(
            claim.id,
            ClaimReview(
                approved=True,
                permitted_use=ClaimPermittedUse.APPLICATIONS,
            ),
        )
    summary = next(item for item in service.calculate_experience(profile_id) if item.skill == "bgp")
    assert summary.months == 60
    assert summary.years == 5

    answer = service.add_answer(
        profile_id,
        AnswerLibraryCreate(
            question="How many years of BGP experience do you have?",
            canonical_field="experience.bgp_years",
            answer="Five years of verified BGP experience.",
            evidence_claim_ids=[verified_skill.id, *[claim.id for claim in experience_claims]],
            provenance={"reviewed_by": "user"},
        ),
    )
    assert answer.locked and answer.approved
    results = service.retrieve(
        profile_id,
        RetrievalQuery(query="BGP experience", permitted_use=ClaimPermittedUse.APPLICATIONS),
    )
    assert {result.source_type for result in results} == {"ANSWER", "CLAIM"}
    assert any("Five years" in result.content for result in results)

    answer_row = session.get(AnswerLibraryRow, answer.id)
    assert answer_row is not None
    assert "Five years" not in answer_row.encrypted_answer
    chunks = session.scalars(select(RetrievalChunkRow)).all()
    assert chunks
    assert all("bgp" not in " ".join(chunk.token_hashes_json).casefold() for chunk in chunks)
    assert all("BGP" not in chunk.encrypted_content for chunk in chunks)

    duplicate = service.import_document(
        profile_id,
        file_name="network-resume-v2.txt",
        data=RESUME.replace(b"Docker", b"Kubernetes"),
        kind=DocumentKind.RESUME,
        display_name="Network resume v2",
        variant_label="Network engineering alternate",
        job_family_tags=["network"],
        is_primary=False,
    )
    duplicate_bgp = next(
        claim for claim in duplicate.proposed_claims if claim.canonical_key == "skill.bgp"
    )
    with pytest.raises(CandidateKnowledgeConflictError, match="locked verified fact"):
        service.review_claim(duplicate_bgp.id, ClaimReview(approved=True))
    assert service.list_claims(profile_id)[-1].verification_status in {
        ClaimVerificationStatus.PROPOSED,
        ClaimVerificationStatus.VERIFIED,
    }


def test_pdf_docx_and_rtf_layout_extractors() -> None:
    pdf_buffer = BytesIO()
    canvas = Canvas(pdf_buffer)
    canvas.drawString(72, 720, "PDF resume with Python and BGP")
    canvas.save()
    _, pdf = extract_document("resume.pdf", pdf_buffer.getvalue())
    assert "PDF resume" in pdf.plain_text
    assert pdf.page_count == 1
    assert pdf.blocks[0].page == 1

    docx_buffer = BytesIO()
    document = DocxDocument()
    document.add_heading("DOCX Resume", level=1)
    document.add_paragraph("Python automation engineer")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Certification"
    table.cell(0, 1).text = "CCNP"
    document.save(docx_buffer)
    _, docx = extract_document("resume.docx", docx_buffer.getvalue())
    assert any(block.style == "Heading 1" for block in docx.blocks)
    assert any(block.kind == "TABLE_ROW" and "CCNP" in block.text for block in docx.blocks)

    _, rtf = extract_document(
        "resume.rtf", b"{\\rtf1\\ansi Candidate\\par Python automation\\par CCNP}"
    )
    assert "Python automation" in rtf.plain_text


def test_candidate_knowledge_multipart_api(session: Session, tmp_path: Path) -> None:
    profile_id = _profile(session)
    service = _service(session, tmp_path)
    app.dependency_overrides[get_knowledge_service] = lambda: service
    client = TestClient(app)
    try:
        response = client.post(
            f"/api/v1/knowledge/profiles/{profile_id}/documents",
            files={"file": ("resume.txt", RESUME, "text/plain")},
            data={
                "kind": "RESUME",
                "display_name": "API resume",
                "variant_label": "Infrastructure",
                "job_family_tags": "network,platform",
                "is_primary": "true",
            },
        )
        assert response.status_code == 201
        payload = response.json()
        assert payload["document"]["is_primary"] is True
        assert payload["version"]["media_type"] == "text/plain"
        assert payload["proposed_claims"]
        snapshot = client.get(f"/api/v1/knowledge/profiles/{profile_id}/snapshot").json()
        assert len(snapshot["documents"]) == 1
        assert snapshot["answers"] == []
    finally:
        app.dependency_overrides.clear()
