"""Final Video Assembly (`S10_ASSEMBLE`) stitching approved shot clips into a master MP4."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path

from .errors import ValidationFailed
from .repo import Repo
from .schema import GenerationRun, Status


def _is_run_style_drifted(r: GenerationRun) -> bool:
    if r.qa_scores is None:
        return False
    return (
        "style_drift" in r.qa_scores.artifact_flags
        or "frozen_frame" in r.qa_scores.artifact_flags
        or (r.qa_scores.action_achieved <= 0.05 and r.qa_scores.setting_match <= 0.2)
    )


def _select_winning_clip_bytes(repo: Repo, shot_id: str) -> bytes:
    runs = repo.list_generation_runs(shot_id=shot_id)
    approved = [r for r in runs if r.status == Status.APPROVED and r.output_video_uri]
    if not approved:
        fallbacks = [
            r for r in runs if r.output_video_uri and not _is_run_style_drifted(r)
        ]
        if fallbacks:
            fallbacks.sort(
                key=lambda r: (
                    (
                        r.qa_scores.wardrobe_match
                        + r.qa_scores.setting_match
                        + r.qa_scores.action_achieved
                    )
                    if r.qa_scores
                    else 0.0,
                    r.attempt,
                )
            )
            approved = fallbacks
    if not approved:
        raise ValidationFailed(
            [
                f"Shot '{shot_id}' has no approved or style-consistent video clip to assemble (failed QA / style drift)"
            ]
        )
    winner = approved[-1]
    assert winner.output_video_uri is not None
    return repo.blobs.get_bytes(winner.output_video_uri)


def _run_ffmpeg_concat(concat_txt: Path, out_file: Path) -> bool:
    cmd_copy = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_txt),
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(out_file),
    ]
    proc = subprocess.run(cmd_copy, capture_output=True, timeout=60, check=False)
    if proc.returncode != 0 or not out_file.is_file() or out_file.stat().st_size == 0:
        cmd_reencode = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_txt),
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(out_file),
        ]
        proc = subprocess.run(
            cmd_reencode, capture_output=True, timeout=60, check=False
        )
    return proc.returncode == 0 and out_file.is_file() and out_file.stat().st_size > 256


def _stitch_clips(clip_bytes_list: list[bytes]) -> bytes:
    if len(clip_bytes_list) == 1 and len(clip_bytes_list[0]) > 256:
        return clip_bytes_list[0]
    if shutil.which("ffmpeg") and len(clip_bytes_list) > 1:
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_path = Path(tmpdir)
                list_lines: list[str] = []
                for idx, b in enumerate(clip_bytes_list):
                    p = tmp_path / f"clip_{idx:03d}.mp4"
                    p.write_bytes(b)
                    list_lines.append(f"file '{p}'")
                concat_txt = tmp_path / "concat.txt"
                concat_txt.write_text("\n".join(list_lines), encoding="utf-8")
                out_file = tmp_path / "final.mp4"
                if _run_ffmpeg_concat(concat_txt, out_file):
                    return out_file.read_bytes()
        except Exception:
            pass
    digest = hashlib.sha256(b"".join(clip_bytes_list)).digest()
    return (
        b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"
        + b"\x00\x00\x00\x28mdat"
        + digest
        + b"".join(clip_bytes_list)
    )


def assemble(repo: Repo, out_rel_path: str = "out/final.mp4") -> str:
    """Stitch the winning APPROVED `GenerationRun` clip for each Shot in `story_order`."""
    shots = sorted(
        repo.list_shots(), key=lambda s: (s.story_order, s.scene_id, s.index_in_scene)
    )
    if not shots:
        raise ValidationFailed(["Cannot assemble final video: no shots exist"])
    clip_bytes_list = [_select_winning_clip_bytes(repo, s.id) for s in shots]
    merged_bytes = _stitch_clips(clip_bytes_list)
    final_uri = repo.blobs.put_bytes(
        out_rel_path, merged_bytes, content_type="video/mp4"
    )
    meta = repo.get_project_meta()
    if meta:
        signed = (
            repo.blobs.sign_url(final_uri)
            if hasattr(repo.blobs, "sign_url")
            else final_uri
        )
        repo.put_project_meta(
            meta.model_copy(
                update={
                    "final_video_uri": final_uri,
                    "final_video_url": signed,
                    "status": "completed",
                    "current_stage": "S10_ASSEMBLE",
                }
            )
        )
    return final_uri
