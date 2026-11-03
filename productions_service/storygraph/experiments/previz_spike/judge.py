"""Spike judge: per-clip entity/beat metrics, cuts, clip/scene handoff drift, E1 lip movement.

Reuses the keyframe experiment's frame judge (`keyframe_ab.judge.observe_clip`, per-frame
counts + beat adherence) so numbers are comparable with the plate-D1 study; adds a
deterministic layout-drift metric between consecutive clips (Lab ΔE on static cells, the
same guard S8_KEYFRAMES uses) and a VLM lip-movement check for clips with dialogue.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from google import genai
from pydantic import BaseModel, Field

from ...adapters.media_frames import detect_scene_cuts
from ...adapters.vlm import GeminiVLMProvider
from ...keyframes.render.drift import DriftCfg, measure
from ..keyframe_ab.contracts import ClipObservation
from ..keyframe_ab.judge import continuity, frames_1fps, observe_clip
from ..keyframe_ab.metrics import drift_metrics
from ..keyframe_ab.scoring import ShotTruth


class LipObs(BaseModel):
    speaker_visible: bool = False
    mouth_moving: list[bool] = Field(default_factory=list)  # one per frame
    notes: str = ""


def frames_at_fps(clip: Path, out_dir: Path, fps: float) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(clip)]
    subprocess.run(
        [*cmd, "-vf", f"fps={fps},scale=480:-2", str(out_dir / "f_%03d.jpg")],
        check=False,
    )
    return sorted(out_dir.glob("f_*.jpg"))


def lip_movement(
    vlm: GeminiVLMProvider, clip: Path, out: Path, speaker: str
) -> dict[str, float]:
    frames = frames_at_fps(clip, out / "lip" / clip.stem, 4.0)[:32]
    ask = (
        f"Frames at 4 fps from one clip in which {speaker} speaks. For EVERY frame report "
        f"mouth_moving: is {speaker}'s mouth visibly open/articulating (not closed or static)? "
        "speaker_visible: is the speaker's face visible in most frames?"
    )
    obs = vlm.review([f.read_bytes() for f in frames], ask, LipObs)
    moving = obs.mouth_moving or [False]
    changes = sum(1 for a, b in zip(moving, moving[1:], strict=False) if a != b)
    return {
        "lip_moving_rate": round(sum(moving) / len(moving), 3),
        "lip_open_close_changes": float(changes),
        "speaker_visible": float(obs.speaker_visible),
    }


def clip_metrics(
    client: genai.Client, clip: Path, truth: ShotTruth, out: Path
) -> dict[str, float]:
    cached = out / "judge" / f"{clip.stem}.json"
    if cached.is_file():  # resumable: reuse an earlier judgement of the same clip
        obs = ClipObservation.model_validate_json(cached.read_text(encoding="utf-8"))
    else:
        frames = frames_1fps(clip, out / "frames" / clip.stem)
        obs = observe_clip(client, frames, truth.beats, truth.objects, truth.characters)
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(obs.model_dump_json(indent=1), encoding="utf-8")
    base = {k: float(v) for k, v in drift_metrics(obs).items()}
    missing = [c for f in obs.frames for c in f.characters if not c.present]
    base["missing_character_frames"] = float(len(missing))
    base["extra_char_frames"] = float(sum(f.extra_characters > 0 for f in obs.frames))
    base["cuts"] = float(len(detect_scene_cuts(clip)))
    return base


def last_and_first(prev: Path, cur: Path, out: Path) -> tuple[Path, Path]:
    d = out / "handoff"
    d.mkdir(parents=True, exist_ok=True)
    a, b = d / f"{prev.stem}__last.jpg", d / f"{cur.stem}__first.jpg"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-sseof",
            "-0.1",
            "-i",
            str(prev),
            "-frames:v",
            "1",
            str(a),
        ],
        check=False,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(cur),
            "-frames:v",
            "1",
            str(b),
        ],
        check=False,
    )
    return a, b


def handoff(client: genai.Client, prev: Path, cur: Path, out: Path) -> dict[str, float]:
    """VLM continuity score + deterministic static-region drift (no character mask)."""
    a, b = last_and_first(prev, cur, out)
    if not (a.is_file() and b.is_file()):
        return {"handoff_score": 0.0, "layout_drift_bad_fraction": 1.0}
    obs = continuity(client, a, b)
    rep = measure(a.read_bytes(), b.read_bytes(), [], DriftCfg())
    return {
        "handoff_score": float(obs.score),
        "layout_drift_bad_fraction": rep.bad_fraction,
        "same_layout": float(obs.same_objects_and_layout),
    }
