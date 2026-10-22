"""Re-score golden clips with the live eval engine; results append to a JSONL cache.

Already-scored `run_id`s (without error) are skipped, so a re-run only pays for new or failed
clips. One failing clip never aborts the batch (its error is cached and retried next run).
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from ...adapters.embeddings import make_embedder
from ...adapters.media_frames import probe_clip
from ...adapters.transcribe import GeminiTranscriber
from ...adapters.vlm import GeminiVLMProvider
from ...config import Config
from ...qa.critic.checks import CriticThresholds
from ..contracts import EVAL_VERSION, EvalInput, LabelledRef
from ..engine import EvalEngine
from .contracts import CachedScore, ScoreJob

logger = logging.getLogger(__name__)


def build_live_engine(cfg: Config) -> EvalEngine:
    """The engine exactly as `storygraph.eval.run` builds it for real (non-mock) reviews."""
    return EvalEngine(
        vlm=GeminiVLMProvider(cfg.models.critic_vlm),
        gate_cfg=cfg.eval,
        thr=CriticThresholds.from_cfg(cfg.qa),
        embedder=make_embedder(prefer_vertex=True),
        transcriber=GeminiTranscriber(),
        run_cv=True,
    )


def load_cache(path: Path) -> dict[str, CachedScore]:
    """Latest cached score per run_id (later lines win)."""
    if not path.is_file():
        return {}
    rows = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    out: dict[str, CachedScore] = {}
    for ln in rows:
        rec = CachedScore.model_validate_json(ln)
        out[rec.run_id] = rec
    return out


def to_eval_input(job: ScoreJob) -> EvalInput:
    """Engine input for a job: refs and previous-clip last frame loaded from disk."""
    prev = (
        probe_clip(Path(job.prev_clip_path).read_bytes()).last_frame_png
        if job.prev_clip_path
        else None
    )
    refs = [
        LabelledRef(
            label=r.label,
            kind=r.kind,
            entity_names=r.entity_names,
            png=Path(r.path).read_bytes(),
        )
        for r in job.refs
    ]
    return EvalInput(
        clip_path=job.clip_path,
        spec_json=job.spec_json,
        refs=refs,
        prev_last_frame=prev,
        style_guide=job.style_guide,
        shot_id=job.shot_id,
    )


class GoldenScorer:
    """Scores jobs with one shared engine and appends each result to the cache file."""

    def __init__(self, engine: EvalEngine, cache: Path) -> None:
        self.engine = engine
        self.cache = cache
        self._lock = threading.Lock()

    def score(self, job: ScoreJob) -> CachedScore:
        """Score one clip; errors are captured in the record instead of raised."""
        now = datetime.now(UTC).isoformat()
        try:
            report = self.engine.evaluate(to_eval_input(job))
            rec = CachedScore(
                run_id=job.run_id,
                shot_id=job.shot_id,
                report=report,
                engine_version=f"{report.version}/{report.rubric_version}",
                scored_at=now,
            )
        except Exception as exc:  # noqa: BLE001 - one bad clip must not abort the batch
            rec = CachedScore(
                run_id=job.run_id, shot_id=job.shot_id, error=repr(exc), scored_at=now
            )
        self._append(rec)
        return rec

    def _append(self, rec: CachedScore) -> None:
        with self._lock, self.cache.open("a", encoding="utf-8") as fh:
            fh.write(rec.model_dump_json() + "\n")
        _log_scored(rec)


def score_jobs(
    jobs: Iterable[ScoreJob], engine: EvalEngine, cache: Path, workers: int = 6
) -> dict[str, CachedScore]:
    """Score every uncached (or previously failed) job; return the merged cache."""
    done = {k for k, v in load_cache(cache).items() if v.report is not None}
    todo = [j for j in jobs if j.run_id not in done]
    cache.parent.mkdir(parents=True, exist_ok=True)
    scorer = GoldenScorer(engine, cache)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        list(pool.map(scorer.score, todo))
    return load_cache(cache)


def _log_scored(rec: CachedScore) -> None:
    logger.info(
        "golden_clip_scored",
        extra={
            "who": "storygraph.eval.calibration.scorer",
            "where": "GoldenScorer.score",
            "what": "clip_scored" if rec.report else "clip_score_failed",
            "when": rec.scored_at,
            "why": rec.error or "golden-set calibration re-score",
            "how": f"{EVAL_VERSION} live engine",
            "run_id": rec.run_id,
            "overall": rec.report.overall if rec.report else None,
        },
    )


def read_jobs(path: Path) -> list[ScoreJob]:
    """Jobs from a JSONL manifest (one `ScoreJob` per line)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return [ScoreJob.model_validate(json.loads(ln)) for ln in lines if ln.strip()]
