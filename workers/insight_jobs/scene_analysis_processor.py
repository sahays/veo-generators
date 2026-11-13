"""Scene analysis job: probe a video, analyse it window by window, merge a timeline.

Stages (see `StagedJobProcessor` for the job loop and checkpoint helpers):

1. `probe`: download the video, read its duration, detect hard cuts, plan
   the analysis windows. Checkpoint: `probe.json`.
2. `analyze`: one Gemini call per window, at most `WINDOW_CONCURRENCY` at a
   time. Checkpoint per window: `windows/{index}.json`. A window whose answer
   is truncated or unreadable is split in two and retried, to `MAX_SPLIT_DEPTH`.
3. `merge`: combine the windows into `timeline.json`.
4. `filmstrip`: build the thumbnail sprite. A failure here is logged and
   noted on the record; it does not fail the job.

A retried job reuses every checkpoint it finds, so windows that already
succeeded are not sent to the model again.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import asdict, dataclass
from typing import Any, Awaitable, Iterable, Optional

import deps
from ffmpeg_runner import ffprobe_duration, ffprobe_video, run_ffmpeg
from models import UsageMetrics
from scene_detect import detect_cuts
from timeline_merge import (
    combine_window_parts,
    merge_windows,
    normalize_window_result,
    timeline_counts,
)
from timeline_windows import (
    DEFAULT_MAX_WINDOW_SEC,
    Window,
    can_split,
    plan_filmstrip,
    plan_windows,
    split_window,
)

from insight_jobs.staged_processor import (
    JobContext,
    Stage,
    StagedJobProcessor,
    sum_usage,
)

logger = logging.getLogger(__name__)

MAX_WINDOW_SEC = DEFAULT_MAX_WINDOW_SEC
WINDOW_CONCURRENCY = 4
MAX_SPLIT_DEPTH = 2
RECORD_SUMMARY_CHARS = 1500
_FILMSTRIP_TIMEOUT_SEC = 900
# Finish reasons where asking again for less footage can succeed.
_SPLITTABLE_REASONS = frozenset({"", "STOP", "MAX_TOKENS", "RECITATION"})
_WINDOW_MATCH_SEC = 0.01


@dataclass
class _AnalyzeRun:
    """Shared state of one `analyze` stage: the call limiter and a done counter."""

    limiter: asyncio.Semaphore
    total: int
    done: int = 0


def _checkpoint_matches(saved: Optional[dict], window: Window) -> bool:
    """True when a window checkpoint holds a result for exactly this window."""
    stamp = (saved or {}).get("window") or {}
    result = (saved or {}).get("result")
    try:
        same = (
            abs(float(stamp["start_sec"]) - window.start_sec) <= _WINDOW_MATCH_SEC
            and abs(float(stamp["end_sec"]) - window.end_sec) <= _WINDOW_MATCH_SEC
        )
    except (KeyError, TypeError, ValueError):
        return False
    return same and isinstance(result, dict)


async def _gather_all(coros: Iterable[Awaitable[Any]]) -> list[Any]:
    """Await every coroutine to the end, then raise the first failure, if any.

    Unlike a bare `gather`, nothing is left running when an error surfaces, so
    work that succeeded alongside a failure still gets checkpointed.
    """
    outcomes = await asyncio.gather(*coros, return_exceptions=True)
    failures = [o for o in outcomes if isinstance(o, BaseException)]
    if failures:
        raise failures[0]
    return list(outcomes)


def _valid_probe(probe: Optional[dict]) -> bool:
    if not probe or not isinstance(probe.get("cuts"), list):
        return False
    duration = probe.get("duration_sec")
    return isinstance(duration, (int, float)) and duration > 0


def filmstrip_command(src: str, out: str, spec: dict) -> list[str]:
    """ffmpeg argv that renders the whole sprite described by `spec` in one pass.

    `round=up` makes tile `i` the frame at `i * interval_sec`; the filter's
    default rounding would sample half an interval late.
    """
    grid = (
        f"fps=1/{spec['interval_sec']:g}:round=up,"
        f"scale={spec['tile_width']}:{spec['tile_height']},"
        f"tile={spec['columns']}x{spec['rows']}"
    )
    return [
        *("ffmpeg", "-y", "-i", src, "-an", "-vf", grid),
        *("-frames:v", "1", "-q:v", "5", out),
    ]


class SceneAnalysisProcessor(StagedJobProcessor):
    """Processes pending scene analysis jobs."""

    record_prefix = "scene_analysis"
    stages = (
        Stage("probe", 10),
        Stage("analyze", 75, "analyzing"),
        Stage("merge", 5),
        Stage("filmstrip", 10),
    )

    @property
    def name(self) -> str:
        return "scene_analysis"

    @property
    def firestore_update_method(self) -> str:
        return "update_scene_analysis"

    def get_pending_records(self) -> list:
        return deps.firestore_svc.get_scene_analyses(include_archived=False)

    def _log(self, where: str, what: str, why: str, how: str) -> dict[str, str]:
        return {"who": self.name, "where": where, "what": what, "why": why, "how": how}

    def _local_video(self, ctx: JobContext) -> str:
        """Path of the source video on local disk, downloading it on first use."""
        if "local_path" not in ctx.state:
            suffix = os.path.splitext(ctx.record.video_filename or "")[1] or ".mp4"
            path = ctx.tmp.create(suffix=suffix[:8])
            deps.storage_svc.download_to_file(ctx.record.video_gcs_uri, path)
            ctx.state["local_path"] = path
        return ctx.state["local_path"]

    # ── Stage 1: probe ───────────────────────────────────────────────

    def stage_probe(self, ctx: JobContext) -> None:
        probe = self.load_checkpoint(ctx.record_id, "probe")
        if not _valid_probe(probe):
            path = self._local_video(ctx)
            duration = ffprobe_duration(path)
            if duration <= 0:
                raise RuntimeError("The video duration could not be read")
            self.report(ctx, 0.4, "Detecting cuts")
            probe = {"duration_sec": duration, "cuts": detect_cuts(path)}
            self.save_checkpoint(ctx.record_id, "probe", probe)
        duration, cuts = float(probe["duration_sec"]), list(probe["cuts"])
        windows = plan_windows(duration, cuts, MAX_WINDOW_SEC)
        ctx.state.update(duration_sec=duration, cuts=cuts, windows=windows)
        self.report(
            ctx,
            1.0,
            f"{len(windows)} window(s) planned",
            duration_sec=round(duration, 2),
            window_count=len(windows),
        )

    # ── Stage 2: analyze ─────────────────────────────────────────────

    def stage_analyze(self, ctx: JobContext) -> None:
        payloads = self._run_async(self._analyze_all(ctx))
        for payload in payloads:
            self.add_usage(ctx, payload.get("usage"))
        ctx.state["results"] = [payload["result"] for payload in payloads]

    async def _analyze_all(self, ctx: JobContext) -> list[dict]:
        """Resolve every window; finish the others before reporting a failure.

        Windows that succeed are checkpointed even when a sibling fails, so a
        retry only pays for the ones that did not.
        """
        windows: list[Window] = ctx.state["windows"]
        run = _AnalyzeRun(asyncio.Semaphore(WINDOW_CONCURRENCY), len(windows))
        return await _gather_all(self._window_payload(ctx, run, w) for w in windows)

    async def _window_payload(
        self, ctx: JobContext, run: _AnalyzeRun, window: Window
    ) -> dict:
        """Checkpointed result for one planned window, analysing it if needed."""
        name = f"windows/{window.index}"
        payload = await asyncio.to_thread(self.load_checkpoint, ctx.record_id, name)
        if not _checkpoint_matches(payload, window):
            result, usage = await self._analyze_range(ctx, run, window, 0)
            payload = {
                "window": asdict(window),
                "finish_reason": result.pop("finish_reason", ""),
                "result": result,
                "usage": usage.model_dump(),
            }
            await asyncio.to_thread(self.save_checkpoint, ctx.record_id, name, payload)
        run.done += 1
        self.report(ctx, run.done / run.total, f"window {run.done} of {run.total}")
        return payload

    async def _analyze_range(
        self, ctx: JobContext, run: _AnalyzeRun, window: Window, depth: int
    ) -> tuple[dict, UsageMetrics]:
        """Analyse one range; split it in two when the answer is unusable."""
        record, cuts = ctx.record, ctx.state["cuts"]
        async with run.limiter:
            response = await deps.ai_svc.analyze_timeline_window(
                gcs_uri=record.video_gcs_uri,
                mime_type=record.mime_type,
                window=window,
                duration_sec=ctx.state["duration_sec"],
                cuts=cuts,
                focus=record.focus,
                model_id=record.model_id,
                region=record.region,
            )
        reason = getattr(response, "finish_reason", "")
        if response.data and reason != "MAX_TOKENS":
            result = normalize_window_result(response.data, window)
            result["finish_reason"] = reason or "none"
            return result, response.usage
        self._require_splittable(ctx, window, reason, depth)
        halves = await _gather_all(
            self._analyze_range(ctx, run, half, depth + 1)
            for half in split_window(window, cuts)
        )
        usage = response.usage
        for _, half_usage in halves:
            usage = sum_usage(usage, half_usage)
        combined = combine_window_parts([result for result, _ in halves], window)
        combined["finish_reason"] = f"split after {reason or 'none'}"
        return combined, usage

    def _require_splittable(
        self, ctx: JobContext, window: Window, reason: str, depth: int
    ) -> None:
        """Raise unless an unusable window answer is worth retrying in halves."""
        span = f"{window.start_sec:.0f}s-{window.end_sec:.0f}s"
        retry = (
            reason in _SPLITTABLE_REASONS
            and depth < MAX_SPLIT_DEPTH
            and can_split(window)
        )
        logger.warning(
            f"[{self.name}:{ctx.record_id}] Unusable answer for {span} "
            f"(finish_reason={reason or 'none'}, depth={depth}, retry={retry})",
            extra=self._log(
                "_analyze_range",
                f"unusable_window:{span}",
                f"finish_reason={reason or 'none'}",
                "split_and_retry" if retry else "fail_job",
            ),
        )
        if not retry:
            raise RuntimeError(
                f"The model returned no usable analysis for {span} "
                f"(finish reason: {reason or 'none'})"
            )
        ctx.notes.append(
            f"{span} was re-analysed in two halves (finish reason: {reason or 'none'})"
        )

    # ── Stage 3: merge ───────────────────────────────────────────────

    def stage_merge(self, ctx: JobContext) -> None:
        state = ctx.state
        timeline = merge_windows(state["results"], state["duration_sec"], state["cuts"])
        state["timeline"] = timeline
        state["timeline_uri"] = self.save_json(ctx.record_id, "timeline.json", timeline)

    # ── Stage 4: filmstrip ───────────────────────────────────────────

    def stage_filmstrip(self, ctx: JobContext) -> None:
        try:
            spec, uri = self._build_filmstrip(ctx)
        except Exception as exc:
            logger.warning(
                f"[{self.name}:{ctx.record_id}] Filmstrip skipped: {exc}",
                extra=self._log(
                    "stage_filmstrip", "filmstrip_failed", str(exc), "continue"
                ),
            )
            ctx.notes.append("Filmstrip could not be generated")
            return
        ctx.state.update(filmstrip=spec, filmstrip_uri=uri)

    def _build_filmstrip(self, ctx: JobContext) -> tuple[dict, str]:
        """Render the sprite with one ffmpeg call and upload it."""
        src = self._local_video(ctx)
        video = ffprobe_video(src)
        spec = plan_filmstrip(
            ctx.state["duration_sec"], video["width"], video["height"]
        )
        out = ctx.tmp.create(suffix=".jpg")
        run_ffmpeg(
            filmstrip_command(src, out, spec),
            timeout=_FILMSTRIP_TIMEOUT_SEC,
            label="Filmstrip",
        )
        uri = deps.storage_svc.upload_from_file(
            out, self.record_uri(ctx.record_id, "filmstrip.jpg"), "image/jpeg"
        )
        return spec, uri

    # ── Completion ───────────────────────────────────────────────────

    def completion_updates(self, ctx: JobContext) -> dict[str, Any]:
        state, timeline = ctx.state, ctx.state["timeline"]
        return {
            "duration_sec": timeline["duration_sec"],
            "window_count": len(state["windows"]),
            "summary": timeline["summary"][:RECORD_SUMMARY_CHARS],
            "content_title": timeline["content_title"],
            "counts": timeline_counts(timeline),
            "timeline_gcs_uri": state["timeline_uri"],
            "filmstrip_gcs_uri": state.get("filmstrip_uri"),
            "filmstrip": state.get("filmstrip"),
        }
