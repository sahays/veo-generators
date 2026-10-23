"""Render a `KeyframePlan` into validated 1 fps keyframe images anchored on the scene plate.

Constant generation depth: every keyframe is generated from the SAME inputs — the locked
scene plate, one labelled reference board holding every present character/prop sheet, and
(optionally) the previous keyframe as a pose/position-only reference. A keyframe is never an
edit of an edit, so grain, saturation and layout errors cannot compound across seconds or
clips. A second with an empty delta reuses the previous image; frame 0 of a later clip is the
previous clip's last keyframe (shared, never regenerated).

Each attempt is first checked deterministically against the plate (`drift.check_drift`, no
VLM): background drift is rejected and regenerated straight away. Drift-clean attempts get
the structured per-entity VLM check (`validation`). ≤ `max_retries` regenerations with the
issues fed back; the attempt with the fewest issues is kept and stored.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from ...adapters.base import ImageGenerator, VLMProvider
from ..plan.models import Keyframe, KeyframePlan, PlanInput
from ..plate.refboard import compose_board
from . import prompts
from .drift import DriftCfg, DriftReport, check_drift
from .retry import with_retry
from .sink import KeyframeRecord, KeyframeSink, StoredKeyframe
from .validation import KeyframeCheck, check_prompt, compare

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
    metrics: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class ScenePlate:
    """The locked empty-set plate every keyframe of the scene is anchored on."""

    png: bytes
    asset_id: str = ""
    uri: str = ""
    set_pieces: frozenset[str] = frozenset()


@dataclass(frozen=True)
class RendererCfg:
    model: str
    max_retries: int = 2
    aspect_ratio: str = "16:9"
    seed: int = 7
    drift: DriftCfg = field(default_factory=DriftCfg)


@dataclass(frozen=True)
class RenderJob:
    """What to (re)render: plate, shared frame 0, kept prior frames, start, instruction."""

    plate: ScenePlate | None = None
    shared_first: RenderedKeyframe | None = None
    prior: tuple[RenderedKeyframe, ...] = ()
    start: int = 0
    instruction: str = ""


@dataclass
class _Attempt:
    png: bytes = b""
    issues: list[str] = field(default_factory=list)
    attempts: int = 0
    drift: DriftReport | None = None


@dataclass(frozen=True)
class _Request:
    frame: Keyframe
    prompt: str
    images: list[bytes]
    prev: bytes | None
    drawn: list[str]
    occupied_x: list[float]


def _drift_metrics(report: DriftReport | None) -> dict[str, float]:
    if report is None:
        return {}
    keys = ("bad_fraction", "chroma_ratio", "contrast_ratio")
    return {k: float(v) for k, v in asdict(report).items() if k in keys}


DRIFT_PENALTY = 100  # a drifted background outranks any number of entity issues


def _score(got: _Attempt) -> int:
    drifted = got.drift is not None and not got.drift.ok
    return len(got.issues) + (DRIFT_PENALTY if drifted else 0)


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

    def _request(
        self, inp: PlanInput, frame: Keyframe, plate: ScenePlate, prev: bytes | None
    ) -> _Request:
        pieces = set(plate.set_pieces)
        entries = prompts.board_entries(inp, frame, pieces)
        board, labels = compose_board(
            [(name, self._bytes(uri)) for name, uri in entries]
        )
        props = prompts.drawn_props(frame, pieces)
        prompt = prompts.frame_prompt(inp, frame, pieces, labels, prev is not None)
        images = [plate.png, *([board] if board else []), *([prev] if prev else [])]
        occupied = [c.x for c in frame.characters] + [
            o.x for o in props if o.x is not None
        ]
        return _Request(frame, prompt, images, prev, [o.name for o in props], occupied)

    def _judge(self, req: _Request, png: bytes, plate: ScenePlate) -> _Attempt:
        drift = check_drift(plate.png, png, req.occupied_x, self.cfg.drift)
        if not drift.ok:
            return _Attempt(png, [f"background drift: {drift.reason}"], drift=drift)
        ask = check_prompt(req.frame, req.drawn, with_previous=req.prev is not None)
        shown = [req.prev, png] if req.prev is not None else [png]
        check = with_retry(
            lambda: self.vlm.review(shown, ask, KeyframeCheck), "kf.check"
        )
        return _Attempt(png, compare(req.frame, check, req.drawn), drift=drift)

    def _checked(self, req: _Request, plate: ScenePlate) -> _Attempt:
        """Generate -> drift guard -> structured check; ≤ max_retries regenerations."""
        best = _Attempt()
        issues: list[str] = []
        for attempt in range(self.cfg.max_retries + 1):
            text = req.prompt + prompts.retry_suffix(issues)
            png = with_retry(
                lambda: self.image_gen.generate(
                    text, req.images, self.cfg.aspect_ratio, self.cfg.seed + attempt
                ),
                "kf.generate",
            )
            got = self._judge(req, png, plate)
            issues = got.issues
            if not best.png or _score(got) < _score(best):
                best = got
            best.attempts = attempt + 1
            if not issues:
                break
        return best

    def _store(
        self, plan: KeyframePlan, frame: Keyframe, prompt: str, got: _Attempt
    ) -> RenderedKeyframe:
        metrics = _drift_metrics(got.drift)
        rec = KeyframeRecord(
            plan,
            frame,
            got.png,
            prompt,
            self.cfg.model,
            got.attempts,
            tuple(got.issues),
            metrics,
        )
        stored = self.sink.save(rec)
        _log_keyframe(plan, frame, got, stored)
        return RenderedKeyframe(
            frame.t, got.png, stored, got.attempts, tuple(got.issues), metrics=metrics
        )

    def render(
        self, inp: PlanInput, plan: KeyframePlan, job: RenderJob
    ) -> list[RenderedKeyframe]:
        """Keyframes of `plan` anchored on `job.plate`. `job.shared_first` IS frame 0;
        `job.prior[:job.start]` are kept and frames from `job.start` on are re-derived
        (human regenerate), the first of them with `job.instruction`."""
        if job.plate is None:
            raise ValueError("keyframe rendering requires the scene plate")
        out = _seed_frames(job)
        for frame in plan.keyframes[len(out) :]:
            if out and not frame.delta and frame.t != job.start:
                out.append(_reuse(out[-1], frame.t))
                continue
            req = self._request(inp, frame, job.plate, out[-1].png if out else None)
            if frame.t == job.start and job.instruction:
                req = _with_instruction(req, job.instruction)
            out.append(
                self._store(plan, frame, req.prompt, self._checked(req, job.plate))
            )
        return out


def _with_instruction(req: _Request, instruction: str) -> _Request:
    text = f"{req.prompt}\nAdditional human instruction: {instruction}"
    return _Request(req.frame, text, req.images, req.prev, req.drawn, req.occupied_x)


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
        metrics=prev.metrics,
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
            "how": "plate + ref board (+ previous pose) generation, drift guard, VLM check",
            "issues": got.issues,
            "drift": _drift_metrics(got.drift),
            "plan_hash": plan.plan_hash,
        },
    )
