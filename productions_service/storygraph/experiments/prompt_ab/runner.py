"""Render the case x variant x sample matrix through the production Omni adapter.

Every variant goes through `GeminiVideoGenerator.generate` with an identical `RenderPackage`
except `compiled_prompt`, so the role-tag header, first-frame binding, reference order and
captions are byte-identical across variants (the exact request text is saved for audit).
Renders are resumable (existing clips are skipped) and logged one JSON line each.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from ...adapters.gemini_video import GeminiVideoGenerator
from ...adapters.omni.fallback import build_ladder
from ...adapters.omni.package import RenderPackage
from ...adapters.omni.safety import select_safety_profile
from ...config import VideoProviderCfg
from ...errors import StoryGraphError
from ...omni.spec import OmniClipSpec
from .cases import MAX_IMAGES
from .contracts import PromptVariant, RenderRecord, ShotCase, VariantId
from .variants.builders import BUILDERS

logger = logging.getLogger(__name__)
MODEL_ID = "gemini-omni-1.1-flash-preview"
# Published Omni rate is ~$0.10 per output second at 720p; used as an upper bound for 360p.
USD_PER_SECOND = 0.10


def build_prompt(case: ShotCase, variant: VariantId) -> PromptVariant:
    spec = OmniClipSpec.model_validate_json(case.spec_json)
    text = BUILDERS[variant](spec, bool(case.first_frame_uri))
    return PromptVariant(case.case_id, variant, text, len(text.split()))


def make_package(case: ShotCase, prompt: str, sample: int) -> RenderPackage:
    """Identical package for every variant of a case; only `compiled_prompt` differs."""
    spec = OmniClipSpec.model_validate_json(case.spec_json)
    return RenderPackage(
        shot_id=f"ab_{case.case_id}",
        compiled_prompt=prompt,
        negative_prompt="",
        reference_asset_ids=[lbl.asset_id for lbl in case.labels],
        reference_uris=[lbl.uri for lbl in case.labels],
        first_frame_asset_id=None,
        first_frame_uri=case.first_frame_uri,
        duration_s=spec.clip.duration_s,
        aspect_ratio=spec.clip.aspect,
        seed=sample,
        package_hash="",
        resolution="360p",
        reference_labels=case.labels,
        project_id=case.project_id,
        visual_style_preset=case.visual_style_preset,
        language=case.language,
    )


def primary_request(package: RenderPackage) -> tuple[str, tuple[str, ...]]:
    """(full request text blocks joined, image uris) exactly as the primary rung sends them."""
    profile = select_safety_profile(package.visual_style_preset, package.language)
    req = build_ladder(package, profile, MAX_IMAGES, "tag")[0].request
    texts = [b["text"] for b in req.blocks if b["type"] == "text"]
    return "\n---\n".join(texts), req.image_uris


@dataclass(frozen=True)
class Job:
    case: ShotCase
    variant: VariantId
    sample: int


class MatrixRunner:
    """Thread-pooled, resumable renderer writing clips + request audit + renders.jsonl."""

    def __init__(self, out_dir: Path, project: str, workers: int = 6) -> None:
        self.out_dir = out_dir
        self.workers = workers
        caps = VideoProviderCfg(
            provider="veo", model=MODEL_ID, max_reference_images=MAX_IMAGES
        )
        self.gen = GeminiVideoGenerator(caps=caps, project=project, location="global")
        self._lock = threading.Lock()
        (out_dir / "clips").mkdir(parents=True, exist_ok=True)
        (out_dir / "requests").mkdir(parents=True, exist_ok=True)

    def _stem(self, job: Job) -> str:
        return f"{job.case.case_id}__{job.variant}__s{job.sample}"

    def _log(self, rec: RenderRecord) -> None:
        with (
            self._lock,
            (self.out_dir / "renders.jsonl").open("a", encoding="utf-8") as fh,
        ):
            fh.write(json.dumps(rec.to_dict(), ensure_ascii=False) + "\n")

    def _render(self, job: Job) -> RenderRecord:
        stem = self._stem(job)
        clip = self.out_dir / "clips" / f"{stem}.mp4"
        pkg = make_package(
            job.case, build_prompt(job.case, job.variant).prompt, job.sample
        )
        text, uris = primary_request(pkg)
        (self.out_dir / "requests" / f"{stem}.txt").write_text(text, encoding="utf-8")
        sha = hashlib.sha256(text.encode()).hexdigest()[:16]
        started = time.monotonic()
        err = ""
        if not clip.exists():
            try:
                clip.write_bytes(self.gen.generate(pkg))
            except StoryGraphError as exc:  # recorded on the RenderRecord, not raised
                err = str(exc)[:500]
        fb = self.gen.pop_fallback(pkg.shot_id)
        ok = clip.exists()
        rec = RenderRecord(
            case_id=job.case.case_id,
            variant=job.variant,
            sample=job.sample,
            clip_path=str(clip) if ok else None,
            ok=ok,
            latency_s=round(time.monotonic() - started, 1),
            duration_s=pkg.duration_s,
            est_cost_usd=round(pkg.duration_s * USD_PER_SECOND, 3) if ok else 0.0,
            request_text_sha=sha,
            image_uris=uris,
            error=err,
            fallback_level=fb.fallback_level if fb else "primary",
        )
        logger.info(
            "prompt_ab render who=%s what=%s/%s sample=%d ok=%s latency=%.0fs why=ab_experiment",
            MODEL_ID,
            job.case.case_id,
            job.variant,
            job.sample,
            ok,
            rec.latency_s,
        )
        self._log(rec)
        return rec

    def run(self, jobs: Iterable[Job]) -> list[RenderRecord]:
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            return list(pool.map(self._render, jobs))
