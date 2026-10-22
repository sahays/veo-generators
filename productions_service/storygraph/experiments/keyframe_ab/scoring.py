"""Score rendered clips: focused frame judge + drift metrics + the production eval engine.

`python -m storygraph.eval.run` is invoked as a subprocess per clip (same engine as the S9
critic) with the shot's compiled spec, identity/setting refs and the previous shot's clip of
the same chain as `--prev`. Results are cached in `metrics.jsonl` (resumable).
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from google import genai

from ..prompt_ab.frames import contact_sheet, cut_times
from .contracts import ClipMetrics, ClipObservation, RenderRecord
from .judge import frames_1fps, observe_clip
from .metrics import drift_metrics

_PKG_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class ShotTruth:
    """Graph expectations for one shot, identical for every variant."""

    shot_id: str
    spec_path: Path
    beats: tuple[str, ...]
    objects: tuple[str, ...]
    characters: tuple[tuple[str, str, bytes], ...]
    ref_args: tuple[str, ...]


def eval_engine(clip: Path, truth: ShotTruth, prev: Path | None) -> dict[str, object]:
    args = [sys.executable, "-m", "storygraph.eval.run", "--clip", str(clip)]
    args += ["--spec", str(truth.spec_path)]
    for ref in truth.ref_args:
        args += ["--ref", ref]
    if prev is not None and prev.exists():
        args += ["--prev", str(prev)]
    proc = subprocess.run(
        args, capture_output=True, text=True, cwd=_PKG_ROOT, timeout=900, check=False
    )
    start = proc.stdout.find("{")
    return (
        json.loads(proc.stdout[start:]) if start >= 0 else {"error": proc.stderr[-400:]}
    )


def _eval_fields(raw: dict[str, object]) -> dict[str, object]:
    dims = raw.get("dimension_scores") or []
    gate = raw.get("gate") or {}
    return {
        "eval_overall": raw.get("overall"),
        "eval_gate": gate.get("passed") if isinstance(gate, dict) else None,
        "eval_dims": {
            str(d.get("name") or d.get("dimension")): float(d.get("score") or 0.0)
            for d in dims
            if isinstance(d, dict)
        },
    }


def score_clip(
    client: genai.Client,
    rec: RenderRecord,
    truth: ShotTruth,
    prev: Path | None,
    out: Path,
) -> ClipMetrics:
    clip = Path(rec.clip_path or "")
    stem = clip.stem
    frames = frames_1fps(clip, out / "frames" / stem)
    judged, evaled = out / "judge" / f"{stem}.json", out / "eval" / f"{stem}.json"
    judged.parent.mkdir(exist_ok=True)
    evaled.parent.mkdir(exist_ok=True)
    if judged.exists():  # resumable: reuse an earlier judgement of the same clip
        obs = ClipObservation.model_validate_json(judged.read_text(encoding="utf-8"))
    else:
        obs = observe_clip(client, frames, truth.beats, truth.objects, truth.characters)
        judged.write_text(obs.model_dump_json(indent=1), encoding="utf-8")
    contact_sheet(clip, out / "sheets" / f"{stem}.jpg")
    if evaled.exists():
        raw = json.loads(evaled.read_text(encoding="utf-8"))
    else:
        raw = eval_engine(clip, truth, prev)
        evaled.write_text(json.dumps(raw, indent=1), encoding="utf-8")
    return ClipMetrics.model_validate(
        {
            "shot_id": rec.shot_id,
            "variant": rec.variant,
            "sample": rec.sample,
            **drift_metrics(obs),
            "cuts": len(cut_times(clip)),
            **_eval_fields(raw),
        }
    )
