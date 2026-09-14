"""Authenticated historical readiness must be internally consistent, not freshly rescored."""

from collections.abc import Callable
from typing import cast

import pytest
from sqlalchemy import delete, select

from job_apply_pro.storage.models import JobReadinessReviewRow
from job_apply_pro.storage.restore_gate_repository import RestoreGateRepository
from job_apply_pro.storage.restore_history_repository import UNAVAILABLE, RestoreHistoryError
from test_forward_restore_history import _HistoryRestore
from test_forward_restore_history import history as history
from test_restore_history_portal_documents import _admit
from test_restore_history_portal_documents import graph as graph


def _items(payload: dict[str, object], key: str) -> list[dict[str, object]]:
    value = payload[key]
    assert isinstance(value, list) and all(isinstance(item, dict) for item in value)
    return cast(list[dict[str, object]], value)


def _mutate(graph: _HistoryRestore, kind: str, change: Callable[[dict[str, object]], None]) -> None:
    with graph.session() as session:
        row = session.scalar(
            select(JobReadinessReviewRow).where(JobReadinessReviewRow.kind == kind)
        )
        assert row is not None
        context = f"job-readiness:{row.application_id}:{row.id}"
        payload = graph.cipher.decrypt_json(row.encrypted_payload, context=context)
        change(payload)
        row.encrypted_payload = graph.cipher.encrypt_json(payload, context=context)
        # This is authenticated data with the original row/context identity, not
        # a damaged envelope or a comparison failure between different databases.
        assert graph.cipher.decrypt_json(row.encrypted_payload, context=context) == payload
        session.commit()


def _refused(graph: _HistoryRestore) -> None:
    before = graph.database.read_bytes()
    with pytest.raises(RestoreHistoryError) as error:
        _admit(graph)
    assert str(error.value) == UNAVAILABLE
    assert graph.database.read_bytes() == before
    gate = RestoreGateRepository(graph.root)
    assert not gate.blocked()
    assert not (gate.control / "operations").exists()


@pytest.mark.parametrize("field", ["id", "span_id"])
def test_standalone_requirements_cannot_repeat_requirement_or_source_span_identity(
    graph: _HistoryRestore, field: str
) -> None:
    with graph.session() as session:
        session.execute(
            delete(JobReadinessReviewRow).where(JobReadinessReviewRow.kind != "REQUIREMENTS")
        )
        session.commit()
    _admit(graph)

    def repeat(payload: dict[str, object]) -> None:
        requirements = _items(payload, "requirements")
        assert len(requirements) == 2
        requirements[1][field] = requirements[0][field]

    _mutate(graph, "REQUIREMENTS", repeat)
    _refused(graph)


@pytest.mark.parametrize("change", ["empty", "missing", "duplicate"])
def test_qualification_must_cover_each_historical_requirement_exactly_once(
    graph: _HistoryRestore, change: str
) -> None:
    def alter(payload: dict[str, object]) -> None:
        findings = _items(payload, "findings")
        assert len(findings) == 2
        if change == "empty":
            payload["findings"] = []
        elif change == "missing":
            payload["findings"] = findings[:1]
        else:
            payload["findings"] = [findings[0], dict(findings[0])]

    _mutate(graph, "QUALIFICATION", alter)
    _refused(graph)


@pytest.mark.parametrize(
    "change",
    [
        "supported_without_claim",
        "contradicted_without_claim",
        "unknown_with_claim",
        "duplicate_claim",
    ],
)
def test_qualification_evidence_links_have_historical_status_cardinality(
    graph: _HistoryRestore, change: str
) -> None:
    def alter(payload: dict[str, object]) -> None:
        finding = _items(payload, "findings")[0]
        claims = finding["claim_ids"]
        assert isinstance(claims, list) and claims
        if change == "duplicate_claim":
            finding["claim_ids"] = [claims[0], claims[0]]
        elif change == "unknown_with_claim":
            finding["status"] = "UNKNOWN"
        else:
            finding["status"] = "CONTRADICTED" if change.startswith("contradicted") else "SUPPORTED"
            finding["claim_ids"] = []

    _mutate(graph, "QUALIFICATION", alter)
    _refused(graph)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("mandatory_count", 0),
        ("mandatory_supported", 0),
        ("preferred_count", 0),
        ("preferred_supported", 0),
        ("coverage_score", 0.0),
        ("coverage_score", None),
        ("evaluable", False),
        ("eligible", False),
    ],
)
def test_qualification_summary_cannot_disagree_with_its_stored_findings(
    graph: _HistoryRestore, field: str, value: object
) -> None:
    _mutate(graph, "QUALIFICATION", lambda payload: payload.update({field: value}))
    _refused(graph)


@pytest.mark.parametrize("change", ["empty", "preferred_only", "ambiguous"])
def test_consistent_finding_links_do_not_make_absent_or_ambiguous_criteria_eligible(
    graph: _HistoryRestore, change: str
) -> None:
    def requirements(payload: dict[str, object]) -> None:
        items = _items(payload, "requirements")
        if change == "empty":
            payload["requirements"] = []
        elif change == "preferred_only":
            payload["requirements"] = [
                item for item in items if item["classification"] == "PREFERRED"
            ]
        else:
            next(item for item in items if item["classification"] == "PREFERRED")[
                "classification"
            ] = "AMBIGUOUS"

    def qualification(payload: dict[str, object]) -> None:
        findings = _items(payload, "findings")
        if change == "empty":
            payload.update(
                findings=[],
                mandatory_count=0,
                mandatory_supported=0,
                preferred_count=0,
                preferred_supported=0,
            )
        elif change == "preferred_only":
            payload.update(
                findings=[item for item in findings if item["classification"] == "PREFERRED"],
                mandatory_count=0,
                mandatory_supported=0,
            )
        else:
            next(item for item in findings if item["classification"] == "PREFERRED")[
                "classification"
            ] = "AMBIGUOUS"
            payload.update(preferred_count=0, preferred_supported=0)
        # Typed and linked, but this unsupported clearance must not be admitted.
        payload.update(coverage_score=1.0, evaluable=True, eligible=True, eligibility_approved=True)

    _mutate(graph, "REQUIREMENTS", requirements)
    _mutate(graph, "QUALIFICATION", qualification)
    _refused(graph)


@pytest.mark.parametrize("kind", ["QUALIFICATION", "SELECTION"])
def test_unknown_readiness_policy_requires_a_compatible_restore_reader(
    graph: _HistoryRestore, kind: str
) -> None:
    _mutate(graph, kind, lambda payload: payload.update(policy_version="unreviewed-policy/99"))
    _refused(graph)


@pytest.mark.parametrize("change", ["not_approved", "not_eligible"])
def test_selection_requires_historically_eligible_and_explicitly_approved_qualification(
    graph: _HistoryRestore, change: str
) -> None:
    def alter(payload: dict[str, object]) -> None:
        payload["eligibility_approved"] = False
        if change == "not_eligible":
            finding = next(
                item
                for item in _items(payload, "findings")
                if item["classification"] == "MANDATORY"
            )
            finding.update(status="UNKNOWN", claim_ids=[])
            payload.update(mandatory_supported=0, coverage_score=0.5, eligible=False)

    _mutate(graph, "QUALIFICATION", alter)
    # The assessment itself is a valid unapproved/ineligible historical review;
    # only retaining a selection that claims its clearance is inconsistent.
    _refused(graph)


def test_unknown_preferred_finding_does_not_invalidate_historically_supported_mandatory_criteria(
    graph: _HistoryRestore,
) -> None:
    def alter(payload: dict[str, object]) -> None:
        finding = next(
            item for item in _items(payload, "findings") if item["classification"] == "PREFERRED"
        )
        finding.update(status="UNKNOWN", claim_ids=[])
        payload.update(preferred_supported=0, coverage_score=0.5)

    _mutate(graph, "QUALIFICATION", alter)
    before = graph.database.read_bytes()
    _admit(graph)
    assert graph.database.read_bytes() == before
