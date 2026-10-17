"""Human/Automated Gate enforcement (`G1`, `G2`, `G3`) for the StoryGraph pipeline."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from ..audit import append_audit
from ..errors import GateBlocked
from ..repo import Repo
from ..schema import Gate, Role, Status

GateId = Literal["G1", "G2", "G3"]

GATE_FOR_STAGE: dict[str, GateId] = {
    "S1_EXTRACT": "G1",
    "S3_DESIGN": "G2",
    "S5_MUSIC": "G3",
}


def ensure_gate(repo: Repo, gate_id: GateId, stage: str) -> Gate:
    existing = repo.get_gate(gate_id)
    if existing:
        return existing
    gate = Gate(
        id=gate_id,
        created_by=Role.PIPELINE,
        status=Status.PROPOSED,
        gate_id=gate_id,
        stage=stage,
        decision="pending",
    )
    return repo.set_gate(gate)


def require_gate(repo: Repo, gate_id: GateId) -> Gate:
    gate = repo.get_gate(gate_id)
    if not gate or gate.decision != "approved":
        raise GateBlocked(gate_id)
    return gate


def approve_gate(
    repo: Repo,
    gate_id: GateId,
    reviewer: str = "studio_user",
    notes: str | None = None,
) -> Gate:
    existing = repo.get_gate(gate_id)
    stage = existing.stage if existing else ""
    gate = Gate(
        id=gate_id,
        created_by=Role.HUMAN,
        status=Status.APPROVED,
        gate_id=gate_id,
        stage=stage,
        decision="approved",
        reviewer=reviewer,
        notes=notes,
        decided_at=datetime.now(UTC),
    )
    saved = repo.set_gate(gate)

    # When G2 is approved, automatically promote all PROPOSED Appearances and Assets to APPROVED
    if gate_id == "G2":
        for app in repo.list_appearances(active_only=True):
            if app.status == Status.PROPOSED or app.status == Status.DRAFT:
                repo.update_appearance_status(app.id, Status.APPROVED)
        for asset in repo.list_assets():
            if asset.status == Status.PROPOSED or asset.status == Status.DRAFT:
                repo.update_asset(asset.id, status=Status.APPROVED)

    append_audit(
        repo.store,
        Role.HUMAN,
        "approve_gate",
        gate_id,
        existing.version if existing else None,
        saved.version,
        f"Approved gate {gate_id} by {reviewer}",
    )
    return saved


def reject_gate(
    repo: Repo,
    gate_id: GateId,
    reviewer: str = "studio_user",
    notes: str = "Revision requested",
) -> Gate:
    existing = repo.get_gate(gate_id)
    stage = existing.stage if existing else ""
    gate = Gate(
        id=gate_id,
        created_by=Role.HUMAN,
        status=Status.DRAFT,
        gate_id=gate_id,
        stage=stage,
        decision="rejected",
        reviewer=reviewer,
        notes=notes,
        decided_at=datetime.now(UTC),
    )
    saved = repo.set_gate(gate)
    append_audit(
        repo.store,
        Role.HUMAN,
        "reject_gate",
        gate_id,
        existing.version if existing else None,
        saved.version,
        f"Rejected gate {gate_id}: {notes}",
    )
    return saved
