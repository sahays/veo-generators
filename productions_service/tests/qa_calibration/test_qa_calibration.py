"""QA calibration: severity model, framing-aware objects, late-cut trimming, early-cut severity.

These pin the gate behaviour that previously rejected acceptable Omni clips: borderline score
breaches, out-of-frame props, shot-size drift and late hard cuts must not block on their own,
while concrete observed defects and an accumulation of mediums still do.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from storygraph.adapters.clip_trim import trim_late_hard_cut
from storygraph.adapters.media_frames import probe_clip
from storygraph.config import Config
from storygraph.qa.critic.checks import CriticThresholds, MediaSignals, check_cuts
from storygraph.qa.critic.gate import evaluate_rubric, gate
from storygraph.qa.critic.rubric import ClipRubric
from storygraph.qa.critic.spec import CriticSpec, parse_compiled_spec

_SPEC = {
    "task": "render_video_clip",
    "clip": {"duration_s": 5.0, "aspect": "16:9", "fps": 24, "audio": {}},
    "subjects": [
        {"id": "S1", "name": "Pip", "kind": "robot", "ref_image": "IMAGE_REF_0"}
    ],
    "objects": [
        {"id": "O1", "name": "Bowl", "start": {"where": "on the counter"}},
    ],
    "camera": {"size": "CU", "angle": "high", "move": "static"},
    "sequence": [{"n": 1, "actor": "S1", "verb": "waves", "target": ""}],
    "constraints": ["single_continuous_take"],
}
_GOOD = ClipRubric.mock_response(
    'RUBRIC_KEYS={"steps":[1],"subjects":["Pip"],"objects":["Bowl"],'
    '"speakers":[],"continuity":false}'
)
_FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")


@pytest.fixture()
def spec() -> CriticSpec:
    return parse_compiled_spec(json.dumps(_SPEC))


@pytest.fixture()
def thr(default_cfg: Config) -> CriticThresholds:
    return CriticThresholds.from_cfg(default_cfg.qa)


def _severities(
    rubric: ClipRubric, spec: CriticSpec, thr: CriticThresholds
) -> dict[str, str]:
    outcome = evaluate_rubric(spec, rubric, MediaSignals(), thr)
    return {f"{d.type}:{d.subject}": d.severity for d in outcome.defects}


def _passes(rubric: ClipRubric, spec: CriticSpec, thr: CriticThresholds) -> bool:
    return gate(evaluate_rubric(spec, rubric, MediaSignals(), thr).defects, thr).passed


def _object(**update: object) -> ClipRubric:
    return _GOOD.model_copy(
        update={"objects": [_GOOD.objects[0].model_copy(update=update)]}
    )


def test_borderline_score_alone_passes(spec: CriticSpec, thr: CriticThresholds) -> None:
    near = _GOOD.model_copy(update={"physics_plausibility": 0.71})
    assert _severities(near, spec, thr) == {"low_score:physics_plausibility": "low"}
    assert _passes(near, spec, thr)
    far = _GOOD.model_copy(update={"physics_plausibility": 0.52})
    assert _severities(far, spec, thr) == {"low_score:physics_plausibility": "medium"}
    assert _passes(far, spec, thr)


def test_three_mediums_block_two_pass(spec: CriticSpec, thr: CriticThresholds) -> None:
    two = _GOOD.model_copy(update={"physics_plausibility": 0.5, "wardrobe_match": 0.5})
    assert _passes(two, spec, thr)
    reversed_cam = two.camera.model_copy(update={"move_matches": False})
    three = two.model_copy(update={"camera": reversed_cam})
    assert list(_severities(three, spec, thr).values()) == ["medium"] * 3
    assert not _passes(three, spec, thr)


def test_shot_size_mismatch_is_low(spec: CriticSpec, thr: CriticThresholds) -> None:
    cam = _GOOD.camera.model_copy(update={"size_matches": False, "observed": "wide"})
    rubric = _GOOD.model_copy(
        update={"camera": cam, "drift_flags": ["framing_mismatch"]}
    )
    sev = _severities(rubric, spec, thr)
    assert sev == {
        "camera_mismatch:camera": "low",
        "critic_flag:framing_mismatch": "low",
    }
    assert _passes(rubric, spec, thr)


def test_out_of_frame_object_is_not_missing(
    spec: CriticSpec, thr: CriticThresholds
) -> None:
    unseen = {"max_instances_seen": 0, "start_matches": False, "end_matches": False}
    out = _object(in_frame_expected=False, evidence="CU on Pip's face", **unseen)
    assert _severities(out, spec, thr) == {"missing_object:Bowl": "low"}
    assert _passes(out, spec, thr)
    crop = _object(
        in_frame_expected=True, evidence="Not seen within the framed crop", **unseen
    )
    assert _severities(crop, spec, thr) == {"missing_object:Bowl": "low"}
    gone = _object(
        in_frame_expected=True, evidence="counter empty at t=0.00-5.00s", **unseen
    )
    assert _severities(gone, spec, thr) == {"missing_object:Bowl": "high"}
    assert not _passes(gone, spec, thr)
    offscreen = json.loads(json.dumps(_SPEC))
    offscreen["objects"][0]["in_frame"] = False
    dressing = parse_compiled_spec(json.dumps(offscreen))
    assert _severities(gone, dressing, thr) == {"missing_object:Bowl": "low"}


def _make_clip(path: Path, red_s: float, blue_s: float) -> None:
    """Two colour segments (one hard cut) with a continuous sine audio track."""
    total = red_s + blue_s
    cmd = ["ffmpeg", "-y", "-hide_banner"]
    for color, secs in (("red", red_s), ("blue", blue_s)):
        cmd += ["-f", "lavfi", "-i", f"color=c={color}:s=160x90:r=24:d={secs}"]
    cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={total}"]
    cmd += ["-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]"]
    cmd += ["-map", "2:a", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac"]
    subprocess.run(
        [*cmd, str(path)],
        capture_output=True,
        stdin=subprocess.DEVNULL,
        check=True,
        timeout=60,
    )


def _stream_duration(path: Path, stream: str) -> float:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            stream,
            "-show_entries",
            "stream=duration",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        stdin=subprocess.DEVNULL,
        check=True,
        timeout=30,
        text=True,
    )
    return float(out.stdout.strip().splitlines()[0])


@pytest.mark.skipif(not _FFMPEG, reason="ffmpeg")
def test_late_cut_is_trimmed_with_audio_in_sync(
    tmp_path: Path, spec: CriticSpec, thr: CriticThresholds
) -> None:
    _make_clip(tmp_path / "late.mp4", 4.0, 1.0)
    result = trim_late_hard_cut((tmp_path / "late.mp4").read_bytes())
    assert result.trimmed and abs(result.cut_at_s - 4.0) < 0.2
    assert abs(result.duration_s - 4.0) < 0.2 and result.original_duration_s > 4.8
    out = tmp_path / "trimmed.mp4"
    out.write_bytes(result.clip_bytes)
    assert abs(_stream_duration(out, "v") - _stream_duration(out, "a")) < 0.1
    probe = probe_clip(result.clip_bytes)
    assert probe.cut_times_s == ()
    sig = MediaSignals(duration_s=probe.duration_s, cut_times_s=probe.cut_times_s)
    assert check_cuts(spec, _GOOD, sig, thr)[0] == []


@pytest.mark.skipif(not _FFMPEG, reason="ffmpeg")
def test_early_cut_is_untrimmed_medium(
    tmp_path: Path, spec: CriticSpec, thr: CriticThresholds
) -> None:
    _make_clip(tmp_path / "early.mp4", 2.0, 3.0)
    raw = (tmp_path / "early.mp4").read_bytes()
    result = trim_late_hard_cut(raw)
    assert not result.trimmed and result.clip_bytes == raw
    probe = probe_clip(raw)
    sig = MediaSignals(duration_s=probe.duration_s, cut_times_s=probe.cut_times_s)
    [cut] = check_cuts(spec, _GOOD, sig, thr)[0]
    assert (cut.type, cut.severity) == ("hard_cut", "medium")
    assert gate([cut], thr).passed
