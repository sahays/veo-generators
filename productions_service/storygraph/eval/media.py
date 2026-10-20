"""Clip probing, labelled image assembly and media signals for one eval run."""

from __future__ import annotations

from ..adapters.media_frames import ClipProbe, detect_frame_anomalies, label_image
from ..qa.critic.checks import MediaSignals
from ..qa.critic.prompt import PREV_FRAME_LABEL, frame_label
from .contracts import LabelledRef
from .metrics.video import VideoMetrics


def assemble_images(
    refs: list[LabelledRef], prev_frame: bytes | None, probe: ClipProbe
) -> tuple[list[bytes], list[str]]:
    """Order: references, previous last frame, then timestamped clip frames (labels burned in)."""
    labelled = [(r.label, r.png) for r in refs]
    if prev_frame:
        labelled.append((PREV_FRAME_LABEL, prev_frame))
    last_idx = len(probe.frames) - 1
    labelled += [
        (frame_label(f.t_s, i == last_idx), f.png) for i, f in enumerate(probe.frames)
    ]
    return [label_image(png, label) for label, png in labelled], [
        lbl for lbl, _ in labelled
    ]


def media_signals(
    probe: ClipProbe, prev_frame: bytes | None, video: VideoMetrics, run_cv: bool
) -> MediaSignals:
    """Deterministic signals; pixel-anomaly flags only for real reviews.

    `frozen_frame` is owned by the temporal freeze metric when frames were decoded, so the
    CV flag is dropped then to avoid double-counting the same defect.
    """
    pngs = [f.png for f in probe.frames]
    cv = detect_frame_anomalies(pngs, prev_last_frame=prev_frame) if run_cv else []
    if video.available:
        cv = [f for f in cv if f != "frozen_frame"]
    return MediaSignals(
        duration_s=probe.duration_s,
        cut_times_s=probe.cut_times_s,
        voiced_ratio=probe.voiced_ratio,
        cv_flags=tuple(cv),
        has_prev_frame=prev_frame is not None,
        frames_sampled=len(probe.frames),
    )
