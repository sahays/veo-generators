"""Face tracking and scene-to-track merging for MediaPipe detections."""

import bisect
import logging
import os
import re
from typing import Any, List, Optional, Tuple

import cv2

logger = logging.getLogger(__name__)

_GAP_SEC = 1.0  # how long an unmatched track survives on its last box
_COST_MAX = 0.7  # (track, detection) pairs above this never link
_HIST_WEIGHT = 0.2  # appearance term (Bhattacharyya) when both sides have one


def _iou(a: dict, b: dict) -> float:
    ax0, ax1 = a["x"] - a["w"] / 2, a["x"] + a["w"] / 2
    ay0, ay1 = a["y"] - a["h"] / 2, a["y"] + a["h"] / 2
    bx0, bx1 = b["x"] - b["w"] / 2, b["x"] + b["w"] / 2
    by0, by1 = b["y"] - b["h"] / 2, b["y"] + b["h"] / 2
    iw = max(0.0, min(ax1, bx1) - max(ax0, bx0))
    ih = max(0.0, min(ay1, by1) - max(ay0, by0))
    inter = iw * ih
    union = a["w"] * a["h"] + b["w"] * b["h"] - inter
    return inter / union if union > 0 else 0.0


def _face_hist(
    frame: Any, f: dict, video_w: int, video_h: int
) -> Optional[List[float]]:
    """L1-normalized HSV histogram (8x4x4) of the face crop — a cheap appearance
    signature for tracker re-ID (survives JSON round-trip into replay fixtures)."""
    x0 = int(max(0.0, f["x"] - f["w"] / 2) * video_w)
    x1 = int(min(1.0, f["x"] + f["w"] / 2) * video_w)
    y0 = int(max(0.0, f["y"] - f["h"] / 2) * video_h)
    y1 = int(min(1.0, f["y"] + f["h"] / 2) * video_h)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    hsv = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1, 2], None, [8, 4, 4], [0, 180, 0, 256, 0, 256])
    total = float(hist.sum()) or 1.0
    return [round(float(v) / total, 5) for v in hist.flatten()]


def _hist_dist(a: List[float], b: List[float]) -> float:
    """Bhattacharyya distance between two L1-normalized histograms (0=same)."""
    bc = sum((pa * pb) ** 0.5 for pa, pb in zip(a, b))
    return max(0.0, 1.0 - bc) ** 0.5


def track_faces(
    frames_data: List[dict],
    max_distance: float = 0.15,
    cuts: Optional[List[float]] = None,
) -> List[dict]:
    """Assign persistent track IDs across frames.

    Returns list of {"time_sec", "tracks": [{"track_id", x, y, w, h,
    "confidence", "mouth"}]}. ``cuts`` (scene-cut timestamps) hard-reset track
    identity — matching across a cut is where v1 invented garbage.
    ``REFRAME_TRACKER=v1`` restores the legacy single-frame matcher.
    """
    if os.getenv("REFRAME_TRACKER", "v2") == "v1":
        return _track_faces_v1(frames_data, max_distance)
    return _track_faces_v2(frames_data, cuts or [])


def _greedy_assign_v2(
    live: List[dict], faces: List[dict], max_step: float
) -> Tuple[dict, set]:
    pairs: List[Tuple[float, int, int]] = []
    for ti, tr in enumerate(live):
        for fi, f in enumerate(faces):
            dist = ((f["x"] - tr["x"]) ** 2 + (f["y"] - tr["y"]) ** 2) ** 0.5
            if dist > max_step * (tr["misses"] + 1):
                continue
            size = 2.0 * max(f.get("w", 0.0), tr["w"]) or 1.0
            cost = 0.6 * (1.0 - _iou(f, tr)) + 0.4 * min(1.0, dist / size)
            if f.get("hist") and tr.get("hist"):
                cost += _HIST_WEIGHT * _hist_dist(f["hist"], tr["hist"])
            if cost < _COST_MAX:
                pairs.append((cost, ti, fi))
    pairs.sort()
    used_t: set = set()
    used_f: set = set()
    assign: dict = {}
    for _, ti, fi in pairs:
        if ti not in used_t and fi not in used_f:
            used_t.add(ti)
            used_f.add(fi)
            assign[fi] = ti
    return assign, used_t


def _emit_frame_tracks_v2(
    faces: List[dict],
    live: List[dict],
    assign: dict,
    used_t: set,
    next_id: int,
    max_misses: int,
) -> Tuple[List[dict], List[dict], int]:
    frame_tracks: List[dict] = []
    new_live: List[dict] = []
    for fi, f in enumerate(faces):
        if fi in assign:
            tid = live[assign[fi]]["tid"]
        else:
            tid = next_id
            next_id += 1
        w, h = f.get("w", 0.0), f.get("h", 0.0)
        frame_tracks.append(
            {
                "track_id": tid,
                "x": f["x"],
                "y": f["y"],
                "w": w,
                "h": h,
                "confidence": f.get("confidence", 0.5),
                "mouth": f.get("mouth"),
            }
        )
        new_live.append(
            {
                "tid": tid,
                "x": f["x"],
                "y": f["y"],
                "w": w,
                "h": h,
                "hist": f.get("hist"),
                "misses": 0,
            }
        )
    for ti, tr in enumerate(live):
        if ti not in used_t:
            tr["misses"] += 1
            if tr["misses"] <= max_misses:
                new_live.append(tr)
    return frame_tracks, new_live, next_id


def _track_faces_v2(frames_data: List[dict], cuts: List[float]) -> List[dict]:
    times = [fd["time_sec"] for fd in frames_data]
    deltas = sorted(b - a for a, b in zip(times, times[1:]) if b > a)
    dt = deltas[len(deltas) // 2] if deltas else 1.0
    max_misses = max(1, round(_GAP_SEC / dt))
    max_step = 0.5 * dt

    next_id, cut_i, prev_t = 0, 0, None
    live: List[dict] = []
    result: List[dict] = []

    for fd in frames_data:
        t = fd["time_sec"]
        while cut_i < len(cuts) and cuts[cut_i] <= t:
            if prev_t is None or cuts[cut_i] > prev_t:
                live = []
            cut_i += 1
        prev_t = t

        faces = fd["faces"]
        assign, used_t = _greedy_assign_v2(live, faces, max_step)
        frame_tracks, live, next_id = _emit_frame_tracks_v2(
            faces, live, assign, used_t, next_id, max_misses
        )
        result.append({"time_sec": t, "tracks": frame_tracks})

    logger.info(
        f"Tracker(v2): {next_id} unique tracks across {len(result)} frames (dt={dt:.2f}s, gap={max_misses} misses)",
        extra={
            "who": "mediapipe_tracking",
            "where": "_track_faces_v2",
            "what": f"{next_id}_tracks",
            "why": "tracking_done",
            "how": "global_greedy",
        },
    )
    return result


def _track_faces_v1(frames_data: List[dict], max_distance: float) -> List[dict]:
    """Legacy tracker: greedy nearest-neighbor vs the previous sample only."""
    next_id = 0
    prev_tracks: List[dict] = []
    result: List[dict] = []

    for fd in frames_data:
        matched = _match_tracks(prev_tracks, fd["faces"], max_distance)
        frame_tracks: List[dict] = []
        new_prev: List[dict] = []
        for face, tid in matched:
            if tid is None:
                tid = next_id
                next_id += 1
            frame_tracks.append(
                {
                    "track_id": tid,
                    "x": face["x"],
                    "y": face["y"],
                    "w": face.get("w", 0.0),
                    "h": face.get("h", 0.0),
                    "confidence": face.get("confidence", 0.5),
                    "mouth": face.get("mouth"),
                }
            )
            new_prev.append({"track_id": tid, "x": face["x"], "y": face["y"]})
        prev_tracks = new_prev
        result.append({"time_sec": fd["time_sec"], "tracks": frame_tracks})

    logger.info(
        f"Tracker: {next_id} unique tracks across {len(result)} frames",
        extra={
            "who": "mediapipe_tracking",
            "where": "_track_faces_v1",
            "what": f"{next_id}_tracks",
            "why": "tracking_done",
            "how": "nearest_neighbor",
        },
    )
    return result


def _match_tracks(prev: List[dict], faces: List[dict], max_dist: float) -> List[tuple]:
    """Match faces to previous tracks by nearest position (v1)."""
    if not prev:
        return [(f, None) for f in faces]
    used: set = set()
    matched: List[tuple] = []
    for face in sorted(faces, key=lambda f: -f.get("confidence", 0)):
        best_tid, best_dist = None, max_dist
        for p in prev:
            if p["track_id"] in used:
                continue
            d = ((face["x"] - p["x"]) ** 2 + (face["y"] - p["y"]) ** 2) ** 0.5
            if d < best_dist:
                best_dist, best_tid = d, p["track_id"]
        if best_tid is not None:
            used.add(best_tid)
        matched.append((face, best_tid))
    return matched


def _scene_focal_points(
    scene: dict,
    tracked_frames: List[dict],
    frame_times: List[float],
    video_duration: float,
) -> List[dict]:
    start = scene.get("start_sec", 0)
    end = scene.get("end_sec", video_duration)
    hint = scene.get("active_subject", "center")
    scene_type = scene.get("scene_type", "general")
    desc = scene.get("description", "")

    lo = bisect.bisect_left(frame_times, start)
    hi = bisect.bisect_right(frame_times, end)
    scene_frames = tracked_frames[lo:hi]
    if not scene_frames:
        return [_center_point(start, desc)]

    pts: List[dict] = []
    for sf in scene_frames:
        if not sf["tracks"]:
            pts.append(_center_point(sf["time_sec"], desc))
            continue
        target = _pick_track(sf["tracks"], hint, scene_type)
        pts.append(
            {
                "time_sec": sf["time_sec"],
                "x": target["x"],
                "y": target["y"],
                "confidence": target["confidence"],
                "description": desc,
            }
        )
    return pts


def merge_scenes_with_tracks(
    scenes: List[dict],
    tracked_frames: List[dict],
    video_duration: float,
) -> List[dict]:
    """Merge Gemini scene hints with MediaPipe tracked positions → focal points."""
    focal_points: List[dict] = []
    frame_times = [f["time_sec"] for f in tracked_frames]
    for scene in scenes:
        focal_points.extend(
            _scene_focal_points(scene, tracked_frames, frame_times, video_duration)
        )

    if not focal_points or focal_points[0]["time_sec"] > 0.1:
        focal_points.insert(0, _center_point(0.0, "start"))
    if focal_points[-1]["time_sec"] < video_duration - 0.5:
        focal_points.append(_center_point(video_duration, "end"))
    focal_points.sort(key=lambda p: p["time_sec"])
    return focal_points


def _pick_track(tracks: List[dict], hint: str, scene_type: str) -> dict:
    """Select which tracked face to follow based on Gemini's hint."""
    h = hint.lower()
    track_match = re.search(r"track\s+([a-z])", h)
    if track_match:
        idx = ord(track_match.group(1)) - ord("a")
        if 0 <= idx < len(tracks):
            return sorted(tracks, key=lambda t: t["track_id"])[idx]

    if "left" in h:
        return min(tracks, key=lambda t: t["x"])
    if "right" in h:
        return max(tracks, key=lambda t: t["x"])
    if scene_type in ("establishing", "wide"):
        return {"x": 0.5, "y": 0.5, "confidence": 0.5, "track_id": -1}
    return max(tracks, key=lambda t: t["confidence"])


def _center_point(time_sec: float, desc: str) -> dict:
    return {
        "time_sec": time_sec,
        "x": 0.5,
        "y": 0.5,
        "confidence": 0.3,
        "description": desc,
    }
