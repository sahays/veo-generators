"""Judge + report stage: score every rendered clip, cross-shot continuity, results table.

Writes `metrics.jsonl`, `continuity.jsonl`, `results.json`, `results.md` and one contact
sheet per variant (`sheets/<variant>__s0.jpg`: the scene's shots stacked in clip order).
"""

from __future__ import annotations

import json
import os
import subprocess
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from statistics import mean

from google import genai

from ...keyframes.plan.graph_source import build_plan_input
from ...keyframes.plan.planner import plan_keyframes
from ...repo import Repo
from .contracts import ClipMetrics, ContinuityObs, RenderRecord
from .judge import continuity
from .packages import latest_run
from .scoring import ShotTruth, score_clip

_TRACKED = ("Wooden Chest", "Blue Cabinet")
_COLUMNS = (
    "chest_dup_rate",
    "chest_present_rate",
    "cabinet_present_rate",
    "cabinet_flicker",
    "outfit_stability",
    "identity_presence",
    "extra_char_rate",
    "action_adherence",
    "cuts",
    "eval_overall",
)


def _truth(repo: Repo, sid: str, out: Path) -> ShotTruth:
    shot = repo.get_shot(sid)
    scene = repo.get_scene(shot.scene_id) if shot else None
    if shot is None or scene is None:
        raise ValueError(f"unknown shot {sid}")
    inp = build_plan_input(repo, scene, shot)
    frame0 = plan_keyframes(inp).keyframes[0]
    spec = out / "specs" / f"{sid}.json"
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text(latest_run(repo, sid).spec_json or "{}", encoding="utf-8")
    chars, refs = [], []
    for c in inp.cast:
        png = repo.blobs.get_bytes(c.ref_uri) if c.ref_uri else b""
        path = out / "refs" / f"{c.entity_id}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png)
        chars.append((c.name, c.wardrobe, png))
        refs.append(f"{c.name}={path}")
    if inp.location_ref_uri:
        loc = out / "refs" / "setting.png"
        loc.write_bytes(repo.blobs.get_bytes(inp.location_ref_uri))
        refs.append(f"setting={loc}")
    names = {o.name for o in frame0.objects if o.visible and o.in_frame} | set(_TRACKED)
    return ShotTruth(
        sid,
        spec,
        tuple(b.action for b in inp.beats),
        tuple(sorted(names)),
        tuple(chars),
        tuple(refs),
    )


def _records(out: Path) -> list[RenderRecord]:
    latest: dict[tuple[str, str, int], RenderRecord] = {}
    for line in (out / "renders.jsonl").read_text(encoding="utf-8").splitlines():
        rec = RenderRecord.model_validate_json(line)
        latest[(rec.shot_id, rec.variant, rec.sample)] = rec
    return [r for r in latest.values() if r.ok]


def _judge(repo: Repo, out: Path, shot_ids: tuple[str, ...]) -> None:
    client = genai.Client(
        vertexai=True, project=os.getenv("GOOGLE_CLOUD_PROJECT"), location="global"
    )
    truths = {sid: _truth(repo, sid, out) for sid in shot_ids}
    recs = _records(out)
    by_key = {(r.variant, r.sample, r.shot_id): r for r in recs}

    def prev_of(rec: RenderRecord) -> Path | None:
        idx = shot_ids.index(rec.shot_id)
        prev = by_key.get((rec.variant, rec.sample, shot_ids[idx - 1])) if idx else None
        return Path(prev.clip_path) if prev and prev.clip_path else None

    with ThreadPoolExecutor(max_workers=3) as pool:
        metrics = list(
            pool.map(
                lambda r: score_clip(client, r, truths[r.shot_id], prev_of(r), out),
                recs,
            )
        )
    (out / "metrics.jsonl").write_text(
        "".join(m.model_dump_json() + "\n" for m in metrics), encoding="utf-8"
    )
    rows: list[str] = []
    for (variant, sample, sid), rec in sorted(by_key.items()):
        prev = prev_of(rec)
        if prev is None:
            continue
        a = sorted((out / "frames" / prev.stem).glob("f_*.jpg"))
        b = sorted((out / "frames" / Path(rec.clip_path or "").stem).glob("f_*.jpg"))
        if a and b:
            obs = continuity(client, a[-1], b[0])
            rows.append(
                json.dumps(
                    {
                        "variant": variant,
                        "sample": sample,
                        "shot_id": sid,
                        **obs.model_dump(),
                    }
                )
            )
    (out / "continuity.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")


def _aggregate(out: Path) -> dict[str, dict[str, float]]:
    metrics = [
        ClipMetrics.model_validate_json(x)
        for x in (out / "metrics.jsonl").read_text().splitlines()
        if x
    ]
    conts = [
        json.loads(x)
        for x in (out / "continuity.jsonl").read_text().splitlines()
        if x.strip()
    ]
    groups: dict[str, list[ClipMetrics]] = defaultdict(list)
    for m in metrics:
        groups[m.variant].append(m)
    table: dict[str, dict[str, float]] = {}
    for variant, ms in sorted(groups.items()):
        row = {
            c: round(mean(float(getattr(m, c) or 0.0) for m in ms), 3) for c in _COLUMNS
        }
        row["gate_pass_rate"] = round(mean(1.0 if m.eval_gate else 0.0 for m in ms), 3)
        vc = [
            ContinuityObs.model_validate(c).score
            for c in conts
            if c["variant"] == variant
        ]
        row["handoff_continuity"] = round(mean(vc), 3) if vc else 0.0
        row["clips"] = len(ms)
        table[variant] = row
    return table


def _variant_sheets(out: Path, shot_ids: tuple[str, ...], variants: list[str]) -> None:
    for variant in variants:
        sheets = [out / "sheets" / f"{sid}__{variant}__s0.jpg" for sid in shot_ids]
        if not all(s.exists() for s in sheets):
            continue
        args = ["ffmpeg", "-y", "-loglevel", "error"]
        for s in sheets:
            args += ["-i", str(s)]
        args += [
            "-filter_complex",
            f"vstack=inputs={len(sheets)}",
            str(out / "sheets" / f"{variant}__s0.jpg"),
        ]
        subprocess.run(args, check=False, capture_output=True, timeout=60)


def run_report_stage(
    repo: Repo, out: Path, shot_ids: tuple[str, ...], judge: bool
) -> int:
    if judge:
        _judge(repo, out, shot_ids)
    table = _aggregate(out)
    _variant_sheets(out, shot_ids, list(table))
    (out / "results.json").write_text(json.dumps(table, indent=1), encoding="utf-8")
    cols = [*_COLUMNS, "gate_pass_rate", "handoff_continuity", "clips"]
    lines = ["| variant | " + " | ".join(cols) + " |", "|" + "---|" * (len(cols) + 1)]
    lines += [
        f"| {v} | " + " | ".join(str(r[c]) for c in cols) + " |"
        for v, r in table.items()
    ]
    (out / "results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0
