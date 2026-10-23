"""Write before/after contact sheets and `metrics.json` for the validated scenes."""

from __future__ import annotations

import json
from pathlib import Path

from ...keyframes.plan.models import KeyframePlan
from ...keyframes.render.drift import DriftCfg
from ...keyframes.render.sink import RepoKeyframeSink
from ...keyframes.stage.scene_plans import scene_planning, stored_scene_plans
from ...repo import Repo
from ...repo.keyframe_sets import KeyframeSetRepo
from .metrics import FrameIn, FrameMetric, ShotMetric, frame_metric, summarise
from .sheets import grid, plate_tile, side_row

CFG = DriftCfg()


def _xs(plan: KeyframePlan, t: int) -> list[float]:
    return [c.x for c in plan.at(t).characters]


def _before_frames(
    before_dir: Path, board: dict[str, dict], shot_id: str
) -> list[FrameIn]:
    shot = board.get(shot_id, {})
    out: list[FrameIn] = []
    for f in shot.get("frames", []):
        path = before_dir / shot_id / f"t{int(f['t']):02d}.png"
        if path.is_file():
            out.append(
                FrameIn(int(f["t"]), path.read_bytes(), f["status"], tuple(f["issues"]))
            )
    return out


def _after_frames(repo: Repo, shot_id: str) -> tuple[list[FrameIn], str]:
    ks = KeyframeSetRepo(repo.store).active_for_shot(shot_id)
    if ks is None:
        return [], "no keyframe set"
    frames = [
        FrameIn(f.t, repo.blobs.get_bytes(f.uri), f.status, tuple(f.issues))
        for f in ks.frames
    ]
    return frames, ks.failure_reason


def _metrics(
    anchor: bytes, frames: list[FrameIn], plan: KeyframePlan
) -> list[FrameMetric]:
    return [frame_metric(anchor, f, _xs(plan, f.t), CFG) for f in frames]


def _scene(
    repo: Repo, scene_id: str, before_dir: Path, board: dict, out: Path
) -> tuple[list[ShotMetric], list[ShotMetric]]:
    scene = repo.get_scene(scene_id)
    planning = scene_planning(repo, scene) if scene else None
    if scene is None or planning is None or planning.spec is None:
        return [], []
    plate = RepoKeyframeSink(repo).load_plate(planning.spec)
    plans = stored_scene_plans(repo, scene)
    first = (
        _before_frames(before_dir, board, planning.shots[0].id)
        if planning.shots
        else []
    )
    before_anchor = first[0].png if first else b""
    after_anchor = plate.png if plate else b""
    befores: list[ShotMetric] = []
    afters: list[ShotMetric] = []
    for sid, sp in plans.items():
        bf, (af, failure) = (
            _before_frames(before_dir, board, sid),
            _after_frames(repo, sid),
        )
        bm, am = (
            _metrics(before_anchor, bf, sp.plan),
            _metrics(after_anchor, af, sp.plan),
        )
        befores.append(ShotMetric(shot_id=sid, frames=bm))
        afters.append(ShotMetric(shot_id=sid, frames=am, failure_reason=failure))
        sheet = grid([side_row("BEFORE", bf, bm), side_row("AFTER", af, am)])
        (out / f"compare_{sid}.jpg").write_bytes(sheet)
    if plate:
        label = f"PLATE {scene_id} " + " ".join(
            f"{k[4:]}={v:.2f}" for k, v in plate.layout.items()
        )
        (out / f"plate_{scene_id}.jpg").write_bytes(
            grid([[plate_tile(plate.png, label[:90])]])
        )
    return befores, afters


def write_report(repo: Repo, scene_ids: list[str], before_dir: Path, out: Path) -> Path:
    raw = json.loads((before_dir / "board.json").read_text(encoding="utf-8"))
    board = {s["shot_id"]: s for s in raw.get("shots", [])}
    sheets = out / "sheets"
    sheets.mkdir(parents=True, exist_ok=True)
    befores: list[ShotMetric] = []
    afters: list[ShotMetric] = []
    for scene_id in scene_ids:
        b, a = _scene(repo, scene_id, before_dir, board, sheets)
        befores += b
        afters += a
    report = {
        "before": summarise("before (edit chain)", befores).model_dump(),
        "after": summarise("after (plate-anchored)", afters).model_dump(),
    }
    path = out / "metrics.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path
