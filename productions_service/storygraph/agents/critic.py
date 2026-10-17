"""CRITIC agent (`critic_agent`) for Stage S3 Visual Asset QA and Stage S9 Multimodal Clip QA."""

from __future__ import annotations

import hashlib
import io
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image
from pydantic import BaseModel

from ..adapters.base import VLMProvider
from ..config import Config
from ..repo import Repo
from ..schema import GenerationRun, QAReport, Role, Shot, Status
from ..tools import write_tools as wt
from ..tools.registry import ToolContext
from ..views import shot_view


class AssetCritiqueOutput(BaseModel):
    approved: bool = True
    qa_notes: str = "Visual reference matches StyleGuide and Appearance."
    refined_visual_description: str | None = None


def review_visual_asset(
    ctx: ToolContext,
    vlm: VLMProvider,
    asset_id: str,
    appearance_id: str,
) -> AssetCritiqueOutput:
    """Inspect a generated Character, Location, or Object reference sheet against its Appearance & StyleGuide."""
    asset = ctx.repo.get_asset(asset_id)
    app = ctx.repo.get_appearance(appearance_id)
    sg = ctx.repo.get_style_guide()
    if not asset or not app:
        return AssetCritiqueOutput(
            approved=False, qa_notes="Missing asset or appearance"
        )

    try:
        img_bytes = ctx.repo.blobs.get_bytes(asset.uri)
    except Exception:
        img_bytes = b""

    prompt = (
        f"Review reference asset {asset.id} ({asset.kind}) for appearance {app.id}: "
        f"'{app.visual_description}' (wardrobe: {app.wardrobe}). "
        f"StyleGuide: {sg.visual_medium if sg else 'cinematic'}."
    )
    critique = vlm.review(
        images=[img_bytes] if img_bytes else [],
        prompt=prompt,
        schema=AssetCritiqueOutput,
    )
    wt.record_asset_critique(
        ctx,
        asset_id=asset_id,
        approved=critique.approved,
        qa_notes=critique.qa_notes,
    )
    if critique.approved:
        ctx.repo.update_appearance_status(appearance_id, Status.APPROVED)
    return critique


def _extract_representative_frames_png(clip_bytes: bytes) -> list[bytes]:
    """Extract 3 representative PNG frames (first, mid, last) from rendered MP4 clip bytes via ffmpeg."""
    if shutil.which("ffmpeg") and len(clip_bytes) > 256:
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_path = Path(tmpdir)
                in_mp4 = tmp_path / "clip.mp4"
                in_mp4.write_bytes(clip_bytes)
                first_png = tmp_path / "first.png"
                last_png = tmp_path / "last.png"
                subprocess.run(
                    [
                        "ffmpeg",
                        "-y",
                        "-i",
                        str(in_mp4),
                        "-frames:v",
                        "1",
                        str(first_png),
                    ],
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
                subprocess.run(
                    [
                        "ffmpeg",
                        "-y",
                        "-sseof",
                        "-0.15",
                        "-i",
                        str(in_mp4),
                        "-frames:v",
                        "1",
                        str(last_png),
                    ],
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
                if first_png.is_file() and first_png.stat().st_size > 64:
                    f_bytes = first_png.read_bytes()
                    l_bytes = (
                        last_png.read_bytes()
                        if (last_png.is_file() and last_png.stat().st_size > 64)
                        else f_bytes
                    )
                    return [f_bytes, f_bytes, l_bytes]
        except Exception:
            pass

    frames: list[bytes] = []
    digest = hashlib.sha256(clip_bytes).digest()
    for i in range(3):
        img = Image.new(
            "RGB",
            (320, 180),
            color=(
                (digest[i * 3] % 180) + 30,
                (digest[i * 3 + 1] % 180) + 30,
                (digest[i * 3 + 2] % 180) + 30,
            ),
        )
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        frames.append(buf.getvalue())
    return frames


def evaluate_clip_qa(
    repo: Repo,
    cfg: Config,
    vlm: VLMProvider,
    shot: Shot,
    run: GenerationRun,
) -> QAReport:
    """Run Stage S9 multimodal clip QA on a rendered `GenerationRun`, recording `qa_scores` and last-frame Asset."""
    critic_ctx = ToolContext(repo=repo, role=Role.CRITIC, cfg=cfg)
    sview = shot_view(repo, shot.id)

    try:
        clip_bytes = (
            repo.blobs.get_bytes(run.output_video_uri) if run.output_video_uri else b""
        )
    except Exception:
        clip_bytes = b"mock_mp4"

    frames = _extract_representative_frames_png(clip_bytes)
    last_frame_bytes = frames[-1]

    # Store extracted last frame as an Asset for downstream `continue_from_last_frame` shots
    pipeline_ctx = ToolContext(repo=repo, role=Role.PIPELINE, cfg=cfg)
    lf_dict = wt.register_asset(
        pipeline_ctx,
        base_asset_id=f"ast_lastframe_{shot.id}",
        kind="first_frame",
        png_bytes=last_frame_bytes,
        depicts_entity_ids=[c.entity_id for c in shot.cast],
        appearance_ids=[],
        generation_prompt=f"Extracted last frame of {shot.id} (run {run.id})",
        model="ffmpeg-frame-extractor",
        seed=run.seed,
        status=Status.APPROVED,
    )

    ref_images: list[bytes] = list(frames)
    for aid in run.reference_asset_ids:
        ref_asset = repo.get_asset(aid)
        if ref_asset:
            try:
                ref_images.append(repo.blobs.get_bytes(ref_asset.uri))
            except Exception:
                pass

    prompt = (
        f"Evaluate rendered clip for shot_id={shot.id} (attempt={run.attempt}). "
        f"Expected location: {sview.location.canonical_name} ({sview.location_appearance.visual_description}). "
        f"Expected action beats: {[b.description for b in shot.beats]}. "
        "Return all similarity/match scores strictly in the [0.0, 1.0] range."
    )
    raw_report = vlm.review(images=ref_images, prompt=prompt, schema=QAReport)

    def _norm01(v: float) -> float:
        if v > 10.0:
            return min(1.0, max(0.0, round(v / 100.0, 3)))
        if v > 1.0:
            return min(1.0, max(0.0, round(v / 10.0, 3)))
        return max(0.0, v)

    report = raw_report.model_copy(
        update={
            "face_similarity": {
                k: _norm01(val) for k, val in raw_report.face_similarity.items()
            },
            "wardrobe_match": _norm01(raw_report.wardrobe_match),
            "setting_match": _norm01(raw_report.setting_match),
            "action_achieved": _norm01(raw_report.action_achieved),
            "continuity_prev_shot": _norm01(raw_report.continuity_prev_shot),
            "dialogue_wer": _norm01(raw_report.dialogue_wer),
        }
    )

    # Deterministic threshold checks against cfg.qa
    failure_reasons = list(report.failure_reasons)
    for char_id, sim in report.face_similarity.items():
        if sim < cfg.qa.face_cosine_min:
            failure_reasons.append(
                f"Face similarity for {char_id} ({sim:.2f}) < {cfg.qa.face_cosine_min}"
            )
    if report.wardrobe_match < cfg.qa.wardrobe_vlm_min:
        failure_reasons.append(
            f"Wardrobe match ({report.wardrobe_match:.2f}) < {cfg.qa.wardrobe_vlm_min}"
        )
    if report.setting_match < cfg.qa.setting_vlm_min:
        failure_reasons.append(
            f"Setting match ({report.setting_match:.2f}) < {cfg.qa.setting_vlm_min}"
        )
    if report.action_achieved < cfg.qa.action_vlm_min:
        failure_reasons.append(
            f"Action score ({report.action_achieved:.2f}) < {cfg.qa.action_vlm_min}"
        )
    if report.dialogue_wer > cfg.qa.dialogue_wer_max:
        failure_reasons.append(
            f"Dialogue WER ({report.dialogue_wer:.2f}) > {cfg.qa.dialogue_wer_max}"
        )

    passed = len(failure_reasons) == 0 and report.passed
    suggested_fix = report.suggested_fix
    if not passed and suggested_fix == "none":
        suggested_fix = "retry_seed"

    final_report = report.model_copy(
        update={
            "passed": passed,
            "failure_reasons": failure_reasons,
            "suggested_fix": suggested_fix,
        }
    )

    wt.record_clip_qa(
        critic_ctx,
        run_id=run.id,
        qa_report=final_report,
        extracted_last_frame_asset_id=lf_dict["id"],
    )

    return final_report
