from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from job_apply_pro.domain.browser import BrowserActionKind
from job_apply_pro.domain.portals import (
    PortalCapability,
    PortalInterventionReason,
    PortalKind,
    PortalPageMatch,
    SupervisedPortalDisposition,
    SupervisedPortalRunSnapshot,
    SupervisedPortalRunState,
    SupervisedPortalStepEvidence,
)
from job_apply_pro.storage.models import (
    SupervisedPortalRunRow,
    SupervisedPortalStepEvidenceRow,
)


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)


class SupervisedPortalRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def save(self, run: SupervisedPortalRunSnapshot) -> SupervisedPortalRunSnapshot:
        row = self._session.get(SupervisedPortalRunRow, run.id)
        values = {
            "portal": run.portal.value,
            "workflow_id": run.workflow_id,
            "browser_session_id": run.browser_session_id,
            "state": run.state.value,
            "current_url": run.current_url,
            "allowed_origins_json": run.allowed_origins,
            "page_fingerprint": run.page_fingerprint,
            "current_match_json": (
                run.current_match.model_dump(mode="json") if run.current_match is not None else None
            ),
            "disposition": run.disposition.value,
            "intervention_reasons_json": [value.value for value in run.intervention_reasons],
            "trace_path": run.trace_path,
            "updated_at": run.updated_at,
        }
        if row is None:
            row = SupervisedPortalRunRow(id=run.id, created_at=run.created_at, **values)
            self._session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
        self._session.commit()
        return run

    def add_evidence(self, evidence: SupervisedPortalStepEvidence) -> SupervisedPortalStepEvidence:
        self._session.add(
            SupervisedPortalStepEvidenceRow(
                id=evidence.id,
                run_id=evidence.run_id,
                sequence=evidence.sequence,
                disposition=evidence.disposition.value,
                capability=(evidence.capability.value if evidence.capability is not None else None),
                page_type=evidence.page_type,
                before_fingerprint=evidence.before_fingerprint,
                after_fingerprint=evidence.after_fingerprint,
                action_kind=(
                    evidence.action_kind.value if evidence.action_kind is not None else None
                ),
                action_fingerprint=evidence.action_fingerprint,
                verified=evidence.verified,
                intervention_reasons_json=[value.value for value in evidence.intervention_reasons],
                created_at=evidence.created_at,
            )
        )
        self._session.commit()
        return evidence

    def next_sequence(self, run_id: str) -> int:
        latest = self._session.scalar(
            select(func.max(SupervisedPortalStepEvidenceRow.sequence)).where(
                SupervisedPortalStepEvidenceRow.run_id == run_id
            )
        )
        return 1 if latest is None else latest + 1

    def get(self, run_id: str) -> SupervisedPortalRunSnapshot | None:
        row = self._session.get(SupervisedPortalRunRow, run_id)
        return self._snapshot(row) if row is not None else None

    def list_runs(self) -> list[SupervisedPortalRunSnapshot]:
        rows = self._session.scalars(
            select(SupervisedPortalRunRow).order_by(SupervisedPortalRunRow.updated_at.desc())
        ).all()
        return [self._snapshot(row) for row in rows]

    def list_evidence(self, run_id: str) -> list[SupervisedPortalStepEvidence]:
        rows = self._session.scalars(
            select(SupervisedPortalStepEvidenceRow)
            .where(SupervisedPortalStepEvidenceRow.run_id == run_id)
            .order_by(SupervisedPortalStepEvidenceRow.sequence)
        ).all()
        return [
            SupervisedPortalStepEvidence(
                id=row.id,
                run_id=row.run_id,
                sequence=row.sequence,
                disposition=SupervisedPortalDisposition(row.disposition),
                capability=(
                    PortalCapability(row.capability) if row.capability is not None else None
                ),
                page_type=row.page_type,
                before_fingerprint=row.before_fingerprint,
                after_fingerprint=row.after_fingerprint,
                action_kind=(
                    BrowserActionKind(row.action_kind) if row.action_kind is not None else None
                ),
                action_fingerprint=row.action_fingerprint,
                verified=row.verified,
                intervention_reasons=[
                    PortalInterventionReason(value) for value in row.intervention_reasons_json
                ],
                created_at=_utc(row.created_at),
            )
            for row in rows
        ]

    def _snapshot(self, row: SupervisedPortalRunRow) -> SupervisedPortalRunSnapshot:
        return SupervisedPortalRunSnapshot(
            id=row.id,
            portal=PortalKind(row.portal),
            workflow_id=row.workflow_id,
            browser_session_id=row.browser_session_id,
            state=SupervisedPortalRunState(row.state),
            current_url=row.current_url,
            allowed_origins=row.allowed_origins_json,
            page_fingerprint=row.page_fingerprint,
            current_match=(
                PortalPageMatch.model_validate(row.current_match_json)
                if row.current_match_json is not None
                else None
            ),
            disposition=SupervisedPortalDisposition(row.disposition),
            intervention_reasons=[
                PortalInterventionReason(value) for value in row.intervention_reasons_json
            ],
            evidence=self.list_evidence(row.id),
            trace_path=row.trace_path,
            created_at=_utc(row.created_at),
            updated_at=_utc(row.updated_at),
        )
