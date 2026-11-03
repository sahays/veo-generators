"""Calibrate the previz master camera to a scene plate (one VLM call + pure geometry).

Pipeline: (1) ONE VLM read (`observe.RoomCornersObs`) gives the room-box corners in the
plate and metric priors; (2) a deterministic line detector (`lines.detect_segments`) finds the
plate's straight edges; (3) Levenberg-Marquardt (`solve`) fits camera height/x/y, pitch,
focal length (FOV) and room width/depth/height to the VLM corners, then repeatedly snaps
detected segments to the projected box edges (shrinking tolerance) and re-fits against those
precise lines plus the depth vanishing point (horizon). Yaw and roll stay 0 (the master
camera faces the back wall square on, as `previz.blocking.project` assumes); lens shifts are
fitted only when `fit_shift=True`. Degenerate plates fall back to the default master camera
with a `fallback_reason`.
"""

from __future__ import annotations

import io
import logging
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final

from PIL import Image

from ...adapters.base import VLMProvider
from ...keyframes.render.retry import with_retry
from ...schemas.previz_scene import CameraRig, Room
from ..blocking.project import Aspect
from .edges import load_gray
from .geometry import (
    IDX,
    Floats,
    Frame,
    depth_vp,
    from_master,
    hfov_deg,
    project_corners,
    to_rig,
    to_room,
)
from .lines import Segment, detect_segments, vanishing_point
from .observe import CORNERS_PROMPT, RoomCornersObs
from .snap import initial_guesses, snap_segments
from .solve import PointObs, Problem, best_of, line_errors, point_errors, rms, solve

_log = logging.getLogger(__name__)
LINE_WIDTH: Final[int] = 800  # analysis width of the line detector
MIN_SEGMENTS: Final[int] = 6
MIN_CORNERS: Final[int] = 3
SNAP_TOLS: Final[tuple[float, ...]] = (0.03, 0.015, 0.008)  # of the image width
POINT_WEIGHT: Final[float] = 0.5  # VLM corners once precise lines are snapped
VP_WEIGHT: Final[float] = 0.3
VP_MIN_INLIERS: Final[int] = 6
MAX_RMS_FRAC: Final[float] = 0.06
FREE: Final[tuple[str, ...]] = (
    "cam_x", "cam_y", "cam_h", "pitch", "focal", "width", "depth", "height",
)  # fmt: skip


@dataclass(frozen=True)
class Calibration:
    """Calibrated (or fallback) master camera + room box for one plate (pixels: plate)."""

    rig: CameraRig
    room: Room
    frame: Frame
    pitch_deg: float
    hfov_deg: float
    corner_rms_px: float = 0.0
    line_rms_px: float = 0.0
    horizon_y_px: float | None = None
    vp_px: tuple[float, float] | None = None
    n_segments: int = 0
    n_line_obs: int = 0
    corners_px: dict[str, tuple[float, float]] = field(default_factory=dict)
    observed_px: dict[str, tuple[float, float]] = field(default_factory=dict)
    fallback_reason: str | None = None


def _frame(png: bytes) -> Frame:
    with Image.open(io.BytesIO(png)) as img:
        return Frame(img.width, img.height)


def _priors(obs: RoomCornersObs) -> dict[str, float]:
    def clamp(v: float, lo: float, hi: float) -> float:
        return min(max(v, lo), hi)

    return {
        "cam_h": clamp(obs.eye_height_m, 0.5, 3.0),
        "width": clamp(obs.room_width_m, 1.5, 30.0),
        "depth": clamp(obs.room_depth_m, 1.5, 30.0),
        "height": clamp(obs.room_height_m, 2.0, 8.0),
    }


def _fallback(frame: Frame, obs: RoomCornersObs | None, aspect: Aspect, why: str,
              n_segments: int = 0) -> Calibration:  # fmt: skip
    """Default master camera for the VLM's room (or the default room)."""
    room = Room()
    if obs is not None:
        p = _priors(obs)
        room = Room(width=p["width"], depth=p["depth"], height=p["height"])
    v = from_master(room, aspect)
    calib = Calibration(
        rig=to_rig(v), room=room, frame=frame, pitch_deg=math.degrees(v[IDX["pitch"]]),
        hfov_deg=hfov_deg(v), n_segments=n_segments, fallback_reason=why,
    )  # fmt: skip
    _log_result(calib)
    return calib


def _points(obs: RoomCornersObs, frame: Frame, weight: float) -> list[PointObs]:
    return [
        PointObs(corner=c, u=x * frame.width, v=y * frame.height, weight=weight)
        for c, (x, y) in sorted(obs.corners().items())
    ]


def _segments(png: bytes, frame: Frame) -> list[Segment]:
    gray = load_gray(png, width=min(LINE_WIDTH, frame.width))
    k = frame.width / gray.shape[1]
    return [s.scaled(k) for s in detect_segments(gray)]


def _refine(
    base: Problem, x: Floats, segments: list[Segment]
) -> tuple[Floats, Problem]:
    """Snap segments at shrinking tolerances, re-fitting with lines + VP each time."""
    prob = base
    for tol in SNAP_TOLS:
        lines = snap_segments(x, base.frame, segments, tol * base.frame.width)
        vp, inliers = vanishing_point(segments, depth_vp(x, base.frame))
        use_vp = vp is not None and inliers >= VP_MIN_INLIERS
        prob = Problem(
            frame=base.frame, free=base.free, priors=base.priors, lines=lines,
            points=[PointObs(p.corner, p.u, p.v, POINT_WEIGHT) for p in base.points],
            vp=vp if use_vp else None, vp_weight=VP_WEIGHT if use_vp else 0.0,
        )  # fmt: skip
        x, _ = solve(prob, x)
    return x, prob


def calibrate_from_obs(
    png: bytes,
    obs: RoomCornersObs,
    aspect: Aspect = "16:9",
    fit_shift: bool = False,
    fit_yaw: bool = True,
) -> Calibration:
    """Pure: plate + VLM observation -> calibrated master camera (or fallback)."""
    frame = _frame(png)
    segments = _segments(png, frame)
    if len(segments) < MIN_SEGMENTS:
        why = f"only {len(segments)} straight edges in the plate (< {MIN_SEGMENTS})"
        return _fallback(frame, obs, aspect, why, len(segments))
    points = _points(obs, frame, 1.0)
    if len(points) < MIN_CORNERS:
        why = f"VLM placed {len(points)} room corners (< {MIN_CORNERS})"
        return _fallback(frame, obs, aspect, why, len(segments))
    free = (
        FREE
        + (("yaw",) if fit_yaw else ())
        + (("shift_x", "shift_y") if fit_shift else ())
    )
    base = Problem(frame=frame, free=free, points=points, priors=_priors(obs))
    px = {p.corner: (p.u, p.v) for p in points}
    x, _ = best_of(base, initial_guesses(px, base.priors, frame))
    x, prob = _refine(base, x, segments)
    corner_rms = rms(point_errors(x, prob))
    if corner_rms > MAX_RMS_FRAC * frame.width:
        why = f"fit did not converge (corner rms {corner_rms:.1f}px)"
        return _fallback(frame, obs, aspect, why, len(segments))
    return _result(x, prob, px, len(segments), corner_rms)


def _result(x: Floats, prob: Problem, observed: dict[str, tuple[float, float]],
            n_segments: int, corner_rms: float) -> Calibration:  # fmt: skip
    vp = depth_vp(x, prob.frame)
    calib = Calibration(
        rig=to_rig(x), room=to_room(x), frame=prob.frame,
        pitch_deg=round(math.degrees(x[IDX["pitch"]]), 3), hfov_deg=round(hfov_deg(x), 3),
        corner_rms_px=round(corner_rms, 2), line_rms_px=round(rms(line_errors(x, prob)), 2),
        horizon_y_px=round(vp[1], 2), vp_px=(round(vp[0], 2), round(vp[1], 2)),
        n_segments=n_segments, n_line_obs=len(prob.lines),
        corners_px={k: (round(u, 1), round(v, 1))
                    for k, (u, v) in project_corners(x, prob.frame).items()},
        observed_px={k: (round(u, 1), round(v, 1)) for k, (u, v) in observed.items()},
    )  # fmt: skip
    _log_result(calib)
    return calib


def calibrate_plate(
    png: bytes,
    vlm: VLMProvider,
    aspect: Aspect = "16:9",
    fit_shift: bool = False,
    fit_yaw: bool = True,
) -> Calibration:
    """ONE VLM call on the plate, then `calibrate_from_obs` (VLM failure -> fallback)."""
    try:
        obs = with_retry(
            lambda: vlm.review([png], CORNERS_PROMPT, RoomCornersObs),
            "previz.camera.calibrate",
        )
    except Exception as exc:  # noqa: BLE001 - any VLM failure degrades to the default camera
        return _fallback(_frame(png), None, aspect, f"VLM read failed: {exc}")
    return calibrate_from_obs(png, obs, aspect, fit_shift, fit_yaw)


def _log_result(c: Calibration) -> None:
    """5W1H log of one calibration (WARNING when it fell back)."""
    _log.log(
        logging.WARNING if c.fallback_reason else logging.INFO,
        "previz camera calibration %s",
        "fell back" if c.fallback_reason else "solved",
        extra={
            "who": "storygraph.previz.camera",
            "where": "previz.camera.calibrate",
            "what": "master_camera_calibration",
            "when": datetime.now(UTC).isoformat(),
            "why": c.fallback_reason or "match the previz camera to the scene plate",
            "how": "VLM room corners + Hough segments -> Levenberg-Marquardt",
            "pitch_deg": c.pitch_deg,
            "hfov_deg": c.hfov_deg,
            "corner_rms_px": c.corner_rms_px,
            "line_rms_px": c.line_rms_px,
            "n_line_obs": c.n_line_obs,
        },
    )
