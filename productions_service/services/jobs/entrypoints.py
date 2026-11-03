"""Async entry points for every long-running production action (202 + background run).

Each `start_*` validates synchronously (cheap document reads: 400 / 404 answered at once),
then submits the existing synchronous service call as a background `JobSpec`. The service
functions are reused unchanged (DRY); their snapshot return values are dropped and only a
small `result` summary is kept on the run.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Literal

from fastapi import HTTPException
from storygraph.pipeline import STAGE_ORDER, Stage
from storygraph.store.base import GraphStore

from ..assembly_service import AssembleMode, assemble_project
from ..keyframes_contract import RegenerateKeyframePayload
from ..keyframes_service import regenerate_shot_keyframe
from ..productions_service import (
    GateDecisionPayload,
    RunPipelinePayload,
    analyze_project_compat,
    approve_project_gate,
    regenerate_project_appearance,
    render_project_compat,
    run_pipeline_for_project,
    run_project_stage,
)
from ..repair_service import (
    RepairShotsPayload,
    regenerate_project_shot,
    repair_project_shots,
)
from ..runtime import get_graph_store, get_repo
from .executor import JobResult, JobSpec, RunPaused, submit_job

_ID = re.compile(r"[A-Za-z0-9_.:-]{1,160}")
_GATES = frozenset({"G1", "G2", "G3"})
_PIPELINE = tuple(st.value for st in STAGE_ORDER[1:])
_STAGE_INDEX: dict[Stage, int] = {st: idx for idx, st in enumerate(STAGE_ORDER)}
Accepted = dict[str, Any]


def _checked(value: str, what: str) -> str:
    if not _ID.fullmatch(value):
        raise HTTPException(status_code=400, detail=f"invalid {what}")
    return value


def _store(project_id: str) -> GraphStore:
    """Graph store of an existing production (legacy docs are auto-seeded once)."""
    store = get_graph_store(_checked(project_id, "project id"))
    if (
        store.get("meta", "project") is None
        and not get_repo(project_id).get_project_meta()
    ):
        raise HTTPException(status_code=404, detail="Production not found")
    return store


def _require(store: GraphStore, collection: str, doc_id: str, what: str) -> None:
    if store.get(collection, _checked(doc_id, what)) is None:
        raise HTTPException(status_code=404, detail=f"{what} {doc_id} not found")


def is_pipeline_stage(stage_id: str) -> bool:
    """S1..S10 run as background jobs; other ids (e.g. previz) keep their own handler."""
    return stage_id in Stage._value2member_map_


def _self_cascading(st: Stage, force: bool) -> bool:
    return st == Stage.S8_KEYFRAMES or (st == Stage.S8_RENDER and force)


def stage_plan(st: Stage, force: bool, cascade: bool) -> tuple[str, ...]:
    """Stages this run executes, in order (progress UI): a cascade runs to S10_ASSEMBLE."""
    if not (cascade or _self_cascading(st, force)):
        return (st.value,)
    return tuple(s.value for s in STAGE_ORDER[_STAGE_INDEX[st] :])


def stage_label(st: Stage, force: bool, cascade: bool) -> str:
    if st == Stage.S8_KEYFRAMES:
        return "Regenerate keyframes" if force else "Resume keyframes"
    verb = "Regenerate" if force else "Run"
    return f"{verb} {st.value}" + (" and downstream" if cascade else "")


def _downstream(project_id: str, st: Stage) -> None:
    """Non-forced downstream stages; S8_KEYFRAMES cascades render -> QA -> assemble itself."""
    for nxt in STAGE_ORDER[_STAGE_INDEX[st] + 1 :]:
        run_project_stage(project_id, nxt.value, False, None)
        if nxt == Stage.S8_KEYFRAMES:
            return


def start_stage_run(
    project_id: str, stage_id: str, force: bool, quality: str | None, cascade: bool
) -> Accepted:
    st, store = Stage(stage_id), _store(project_id)

    def run() -> JobResult:
        run_project_stage(project_id, stage_id, force, quality)
        if cascade and not _self_cascading(st, force):
            _downstream(project_id, st)
        return None

    label, plan = stage_label(st, force, cascade), stage_plan(st, force, cascade)
    return submit_job(store, JobSpec("stage", label, run, plan))


Snapshot = dict[str, Any]


def _pipeline_fn(snapshot_call: Callable[[], Snapshot]) -> JobResult:
    snap = snapshot_call()
    if snap.get("blocked_gate"):
        raise RunPaused(f"Pipeline blocked by unapproved gate {snap['blocked_gate']}")
    return None


def start_pipeline_run(project_id: str, body: RunPipelinePayload | None) -> Accepted:
    store = _store(project_id)
    label = "Auto mode" if body and body.auto_approve_gates else "Run pipeline"

    def run() -> JobResult:
        return _pipeline_fn(lambda: run_pipeline_for_project(project_id, body))

    return submit_job(store, JobSpec("pipeline", label, run, _PIPELINE))


def start_gate_advance(
    project_id: str, gate_id: str, body: GateDecisionPayload | None
) -> Accepted:
    if gate_id not in _GATES:
        raise HTTPException(status_code=400, detail=f"Invalid gate_id '{gate_id}'")
    store = _store(project_id)

    def run() -> JobResult:  # approve inside the run: a 409 leaves the gate untouched
        return _pipeline_fn(
            lambda: approve_project_gate(project_id, gate_id, body, True)
        )

    label = f"Approve {gate_id} and continue"
    return submit_job(store, JobSpec("pipeline", label, run, _PIPELINE))


def start_assembly(project_id: str, mode: AssembleMode) -> Accepted:
    label = (
        "Stitch approved shots" if mode == "approved_only" else "Assemble final video"
    )

    def run() -> JobResult:
        assemble_project(project_id, mode)
        return None

    stages = (Stage.S10_ASSEMBLE.value,)
    return submit_job(_store(project_id), JobSpec("assemble", label, run, stages))


CompatKind = Literal["analyze", "render"]


def start_compat_run(
    project_id: str, body: dict[str, Any] | None, kind: CompatKind
) -> Accepted:
    """Legacy `/analyze` and `/render` endpoints, now asynchronous as well."""
    call = analyze_project_compat if kind == "analyze" else render_project_compat

    def run() -> JobResult:
        call(project_id, body)
        return None

    label = "Analyze story" if kind == "analyze" else "Render production"
    return submit_job(_store(project_id), JobSpec("pipeline", label, run, _PIPELINE))


def start_repair(project_id: str, body: RepairShotsPayload | None) -> Accepted:
    def run() -> JobResult:
        snap = repair_project_shots(project_id, body)
        return {"repair_report": snap["repair_report"], "assembled": snap["assembled"]}

    spec = JobSpec("repair", "Repair failed shots", run, ("S8_REPAIR",))
    return submit_job(_store(project_id), spec)


def start_shot_regenerate(project_id: str, shot_id: str) -> Accepted:
    store = _store(project_id)
    _require(store, "shots", shot_id, "Shot")

    def run() -> JobResult:
        return {
            "repair_report": regenerate_project_shot(project_id, shot_id)[
                "repair_report"
            ]
        }

    spec = JobSpec("shot_regenerate", f"Regenerate {shot_id}", run, ("S8_REPAIR",))
    return submit_job(store, spec)


def start_keyframe_regenerate(
    project_id: str, shot_id: str, t: int, body: RegenerateKeyframePayload | None
) -> Accepted:
    store = _store(project_id)
    _require(store, "shots", shot_id, "Shot")

    def run() -> JobResult:
        strip = regenerate_shot_keyframe(project_id, shot_id, t, body)
        return {"shot_id": shot_id, "keyframe_set_id": strip.get("set_id")}

    label = f"Regenerate keyframes of {shot_id} from t={t}"
    stages = (Stage.S8_KEYFRAMES.value,)
    return submit_job(store, JobSpec("keyframe_regenerate", label, run, stages))


def start_appearance_regenerate(project_id: str, appearance_id: str) -> Accepted:
    store = _store(project_id)
    _require(store, "appearances", appearance_id, "Appearance")

    def run() -> JobResult:
        regenerate_project_appearance(project_id, appearance_id)
        return {"appearance_id": appearance_id}

    label, stages = "Regenerate appearance", (Stage.S3_DESIGN.value,)
    return submit_job(store, JobSpec("appearance_regenerate", label, run, stages))
