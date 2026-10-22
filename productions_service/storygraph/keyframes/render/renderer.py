"""Render a `KeyframePlan` into validated 1 fps keyframe images.

Keyframe 0 is generated from the identity sheets + location plate + plan (or, for the next
shot of a scene, by re-framing the previous shot's final keyframe). Every later keyframe is
an image EDIT of the previous one carrying only that second's delta, so identity, outfits
and layout are inherited instead of re-imagined. A second with an empty delta reuses the
previous image. Each generated keyframe is checked by a cheap VLM against the plan (object
counts, presence, outfit) and regenerated up to `max_retries` times with the issues fed
back; the attempt with the fewest issues is kept and stored as a versioned asset.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ...adapters.base import ImageGenerator, VLMProvider
from ..plan.models import Keyframe, KeyframePlan, PlanInput
from . import prompts
from .sink import KeyframeRecord, KeyframeSink, StoredKeyframe
from .validation import KeyframeCheck, compare

_log = logging.getLogger(__name__)
Fetch = Callable[[str], bytes]


@dataclass(frozen=True)
class RenderedKeyframe:
    t: int
    png: bytes
    stored: StoredKeyframe
    attempts: int
    issues: tuple[str, ...]
    reused: bool = False
    shared_from: str | None = (
        None  # "<shot_id>@t<N>": the previous clip's last keyframe
    )


@dataclass(frozen=True)
class RendererCfg:
    model: str
    max_retries: int = 2
    ref_budget: int = 5
    aspect_ratio: str = "16:9"
    seed: int = 7


@dataclass
class _Attempt:
    png: bytes = b""
    issues: list[str] = field(default_factory=list)
    attempts: int = 0


class KeyframeRenderer:
    def __init__(
        self,
        image_gen: ImageGenerator,
        vlm: VLMProvider,
        sink: KeyframeSink,
        fetch: Fetch,
        cfg: RendererCfg,
    ) -> None:
        self.image_gen, self.vlm, self.sink, self.cfg = image_gen, vlm, sink, cfg
        self._fetch = fetch
        self._cache: dict[str, bytes] = {}

    def _bytes(self, uri: str) -> bytes:
        if uri not in self._cache:
            self._cache[uri] = self._fetch(uri)
        return self._cache[uri]

    def _checked(
        self, frame: Keyframe, prompt: str, images: list[bytes], prev: bytes | None
    ) -> _Attempt:
        """Generate + check against graph state (and the previous keyframe); ≤ max_retries."""
        best = _Attempt()
        issues: list[str] = []
        ask = prompts.check_prompt(frame, with_previous=prev is not None)
        for attempt in range(self.cfg.max_retries + 1):
            png = self.image_gen.generate(
                prompt + prompts.retry_suffix(issues),
                images,
                self.cfg.aspect_ratio,
                self.cfg.seed + attempt,
            )
            shown = [prev, png] if prev is not None else [png]
            check = self.vlm.review(shown, ask, KeyframeCheck)
            issues = compare(frame, check)
            if not best.png or len(issues) < len(best.issues):
                best = _Attempt(png, issues, attempt + 1)
            best.attempts = attempt + 1
            if not issues:
                break
        return best

    def _request(
        self, inp: PlanInput, frame: Keyframe, prev: bytes | None
    ) -> tuple[str, list[bytes]]:
        if prev is None:
            refs = prompts.reference_images(inp, frame, self.cfg.ref_budget)
            return prompts.initial_prompt(inp, frame, refs), [
                self._bytes(r.uri) for r in refs
            ]
        refs = prompts.reference_images(inp, frame, self.cfg.ref_budget - 1)
        identity = [r for r in refs if r.caption.endswith("identity sheet")]
        text = prompts.edit_prompt(frame, identity)
        return text, [prev, *[self._bytes(r.uri) for r in identity]]

    def _store(
        self, plan: KeyframePlan, frame: Keyframe, prompt: str, got: _Attempt
    ) -> RenderedKeyframe:
        rec = KeyframeRecord(
            plan,
            frame,
            got.png,
            prompt,
            self.cfg.model,
            got.attempts,
            tuple(got.issues),
        )
        stored = self.sink.save(rec)
        _log_keyframe(plan, frame, got, stored)
        return RenderedKeyframe(
            frame.t, got.png, stored, got.attempts, tuple(got.issues)
        )

    def render(
        self, inp: PlanInput, plan: KeyframePlan, job: RenderJob | None = None
    ) -> list[RenderedKeyframe]:
        """Keyframes of `plan`. `job.shared_first` IS frame 0 (previous clip's last frame,
        never regenerated); `job.prior[:job.start]` are kept and frames from `job.start` on
        are re-derived (human regenerate), the first of them with `job.instruction`."""
        job = job or RenderJob()
        out = _seed_frames(job)
        for frame in plan.keyframes[len(out) :]:
            if out and not frame.delta and frame.t != job.start:
                out.append(_reuse(out[-1], frame.t))
                continue
            prev = out[-1].png if out else None
            prompt, images = self._request(inp, frame, prev)
            if frame.t == job.start and job.instruction:
                prompt += f"\nAdditional human instruction: {job.instruction}"
            got = self._checked(frame, prompt, images, prev)
            out.append(self._store(plan, frame, prompt, got))
        return out


@dataclass(frozen=True)
class RenderJob:
    """What to (re)render: shared frame 0, kept prior frames, start second, instruction."""

    shared_first: RenderedKeyframe | None = None
    prior: tuple[RenderedKeyframe, ...] = ()
    start: int = 0
    instruction: str = ""


def _seed_frames(job: RenderJob) -> list[RenderedKeyframe]:
    if job.start > 0:
        return list(job.prior[: job.start])
    return [job.shared_first] if job.shared_first is not None else []


def _reuse(prev: RenderedKeyframe, t: int) -> RenderedKeyframe:
    return RenderedKeyframe(
        t,
        prev.png,
        prev.stored,
        0,
        prev.issues,
        reused=True,
        shared_from=prev.shared_from,
    )


def _log_keyframe(
    plan: KeyframePlan, frame: Keyframe, got: _Attempt, stored: StoredKeyframe
) -> None:
    _log.info(
        "keyframe rendered",
        extra={
            "who": "storygraph.keyframes.renderer",
            "where": f"{plan.project_id}/{plan.shot_id}/t{frame.t:02d}",
            "what": f"keyframe {stored.asset_id} ({got.attempts} attempt(s))",
            "when": datetime.now(UTC).isoformat(),
            "why": "1 fps graph-correct keyframe for keyframe-driven animation",
            "how": "image edit of previous keyframe + VLM plan check"
            if frame.t
            else "image generation from identity sheets + plan",
            "issues": got.issues,
            "plan_hash": plan.plan_hash,
        },
    )
