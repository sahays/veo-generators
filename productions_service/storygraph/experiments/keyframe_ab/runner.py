"""Render stage of the keyframe experiment: keyframes once per shot, then the variant matrix.

Each (variant, sample) is one chain over the scene's shots in clip order: variant A binds
the previous clip's last frame as `<FIRST_FRAME>` (production behaviour); B/C start from the
graph keyframes (clip k+1 keyframes are seeded from clip k's final keyframe). Chains run in
parallel; finished clips are skipped on re-run (resumable). One JSON line per render.
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from ...adapters.media_frames import probe_clip
from ...compile import Package
from ...errors import StoryGraphError
from ...keyframes.animate.generator import KeyframeVideoGenerator
from ...keyframes.animate.sources import RenderingSource
from ...keyframes.animate.timing import segment_bounds
from ...keyframes.plan.lint import lint_plan, lint_scene
from ...keyframes.plan.models import KeyframePlan
from ...keyframes.render.renderer import RenderedKeyframe
from ...keyframes.render.sink import StoredKeyframe
from ...repo import Repo
from .contracts import STRATEGY_OF, RenderRecord, VariantId
from .packages import base_package, latest_run

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Chain:
    variant: VariantId
    sample: int
    shot_ids: tuple[str, ...]


class MatrixRenderer:
    def __init__(self, repo: Repo, gen: KeyframeVideoGenerator, out_dir: Path) -> None:
        self.repo, self.gen, self.out = repo, gen, out_dir
        self._lock = threading.Lock()
        for sub in ("clips", "keyframes", "sheets"):
            (out_dir / sub).mkdir(parents=True, exist_ok=True)

    def render_keyframes(self, shot_ids: tuple[str, ...]) -> list[KeyframePlan]:
        """Plan + render + store keyframes in clip order; writes PNGs, plan JSON, lint."""
        plans: list[KeyframePlan] = []
        for sid in shot_ids:
            inp, plan = self.gen.plan_for(sid)
            kdir = self.out / "keyframes" / sid
            cached = _load_cached(kdir, plan)
            if cached and isinstance(self.gen.source, RenderingSource):
                self.gen.source.prime(plan, cached)
            frames = self.gen.keyframes(inp, plan)
            kdir.mkdir(parents=True, exist_ok=True)
            for f in frames:
                (kdir / f"t{f.t:02d}.png").write_bytes(f.png)
            report = {
                "plan": plan.model_dump(),
                "lint": [i.model_dump() for i in lint_plan(plan, inp)],
                "frames": [
                    {
                        "t": f.t,
                        "asset": f.stored.asset_id,
                        "uri": f.stored.uri,
                        "attempts": f.attempts,
                        "issues": list(f.issues),
                        "reused": f.reused,
                    }
                    for f in frames
                ],
            }
            (kdir / "plan.json").write_text(
                json.dumps(report, indent=1), encoding="utf-8"
            )
            _tile(kdir, self.out / "sheets" / f"{sid}__keyframes.jpg")
            plans.append(plan)
        scene_lint = [i.model_dump() for i in lint_scene(plans)]
        (self.out / "keyframes" / "scene_lint.json").write_text(
            json.dumps(scene_lint), encoding="utf-8"
        )
        return plans

    def _first_frame(self, prev_clip: Path | None, stem: str) -> str | None:
        if prev_clip is None or not prev_clip.exists():
            return None
        png = probe_clip(prev_clip.read_bytes()).last_frame_png
        return self.repo.blobs.put_bytes(
            f"kf_ab/lastframes/{stem}.png", png, "image/png"
        )

    def _package(self, sid: str, chain: Chain, prev_clip: Path | None) -> Package:
        shot = self.repo.get_shot(sid)
        if shot is None:
            raise StoryGraphError(f"unknown shot {sid}")
        pkg = base_package(self.repo, shot, latest_run(self.repo, sid))
        if chain.variant != "A_direct":
            return pkg
        stem = f"{sid}__{chain.variant}__s{chain.sample}"
        return replace(pkg, first_frame_uri=self._first_frame(prev_clip, stem))

    def _render(self, sid: str, chain: Chain, prev_clip: Path | None) -> RenderRecord:
        clip = self.out / "clips" / f"{sid}__{chain.variant}__s{chain.sample}.mp4"
        started, err = time.monotonic(), ""
        strategy = STRATEGY_OF[chain.variant]
        if not clip.exists():
            try:
                clip.write_bytes(
                    self.gen.generate_with(
                        self._package(sid, chain, prev_clip), strategy
                    )
                )
            except (StoryGraphError, subprocess.CalledProcessError, ValueError) as exc:
                err = str(exc)[:500]
        calls = len(
            segment_bounds(round(self._duration(sid)), self.gen.caps.keyframe_stride_s)
        )
        rec = RenderRecord(
            shot_id=sid,
            variant=chain.variant,
            sample=chain.sample,
            clip_path=str(clip) if clip.exists() else None,
            ok=clip.exists(),
            latency_s=round(time.monotonic() - started, 1),
            omni_calls=calls if strategy == "keyframe_interp" else 1,
            error=err,
        )
        self._log(rec)
        return rec

    def _duration(self, sid: str) -> float:
        shot = self.repo.get_shot(sid)
        return shot.duration_s if shot else 9.0

    def _chain(self, chain: Chain) -> list[RenderRecord]:
        out: list[RenderRecord] = []
        prev: Path | None = None
        for sid in chain.shot_ids:
            rec = self._render(sid, chain, prev)
            out.append(rec)
            prev = Path(rec.clip_path) if rec.clip_path else None
        return out

    def run(self, chains: list[Chain], workers: int) -> list[RenderRecord]:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            return [r for recs in pool.map(self._chain, chains) for r in recs]

    def _log(self, rec: RenderRecord) -> None:
        with self._lock, (self.out / "renders.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(rec.model_dump_json() + "\n")
        _log.info(
            "keyframe_ab render",
            extra={
                "who": "storygraph.experiments.keyframe_ab",
                "where": f"{rec.shot_id}/{rec.variant}/s{rec.sample}",
                "what": f"render ok={rec.ok} calls={rec.omni_calls}",
                "when": datetime.now(UTC).isoformat(),
                "why": "keyframe render-strategy experiment",
                "how": STRATEGY_OF[rec.variant],
                "error": rec.error,
            },
        )


def _load_cached(kdir: Path, plan: KeyframePlan) -> list[RenderedKeyframe]:
    """Keyframes saved by an earlier run of the same plan hash (empty = none)."""
    path = kdir / "plan.json"
    if not path.is_file():
        return []
    saved = json.loads(path.read_text(encoding="utf-8"))
    if saved["plan"]["plan_hash"] != plan.plan_hash:
        return []
    return [
        RenderedKeyframe(
            f["t"],
            (kdir / f"t{f['t']:02d}.png").read_bytes(),
            StoredKeyframe(f["asset"], f["uri"]),
            f["attempts"],
            tuple(f["issues"]),
            f["reused"],
        )
        for f in saved["frames"]
    ]


def _tile(frames_dir: Path, out: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-framerate",
            "1",
            "-i",
            str(frames_dir / "t%02d.png"),
        ]
        + ["-vf", "scale=320:-1,tile=5x2", "-frames:v", "1", str(out)],
        check=False,
        capture_output=True,
        timeout=60,
    )
