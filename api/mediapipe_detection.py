"""MediaPipe-based face detection and tracking for smart reframing.

Uses the MediaPipe Tasks API (v0.10+) with downloaded model files.
Falls back to OpenCV Haar cascade if MediaPipe fails to initialize.
"""

import bisect
import logging
import os
import tempfile
import urllib.request
from typing import List, Optional

import cv2

logger = logging.getLogger(__name__)

# Model URLs (Google's hosted models). Short-range BlazeFace is a selfie-
# distance model — it misses small/distant/profile faces in cinematic wide
# shots — so the full-range variant runs alongside it by default and the two
# detection sets are IoU-NMS merged (REFRAME_FACE_MODEL=both|short|full).
_FACE_MODEL_URLS = {
    "short": "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/latest/blaze_face_short_range.tflite",
    "full": "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_full_range/float16/latest/blaze_face_full_range.tflite",
}
_face_detectors: dict = {}  # variant -> detector | False (cached init failure)
_NMS_IOU = 0.5

# Person detector (EfficientDet-Lite) — catches bodies when no frontal face is
# visible (distant, profile, low-light, or walking away from camera).
_OBJECT_MODEL_URL = "https://storage.googleapis.com/mediapipe-models/object_detector/efficientdet_lite0/int8/latest/efficientdet_lite0.tflite"
_OBJECT_MODEL_PATH = None
_object_detector = None  # None = not tried; False = init failed (cached)


def _face_variants() -> List[str]:
    mode = os.getenv("REFRAME_FACE_MODEL", "both")
    return ["short", "full"] if mode == "both" else [mode]


def _ensure_model(variant: str = "short"):
    """Download a face detection model variant if not cached."""
    cache_dir = os.path.join(tempfile.gettempdir(), "mediapipe_models")
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, f"blaze_face_{variant}_range.tflite")
    if not os.path.exists(path):
        logger.info(f"Downloading MediaPipe face model ({variant}) to {path}...")
        urllib.request.urlretrieve(_FACE_MODEL_URLS[variant], path)
    return path


def _get_face_detector(variant: str = "short"):
    """Lazy-init one MediaPipe FaceDetector variant (cached, incl. failures)."""
    cached = _face_detectors.get(variant)
    if cached is not None:
        return cached or None  # False (cached failure) → None
    try:
        import mediapipe as mp

        model_path = _ensure_model(variant)
        options = mp.tasks.vision.FaceDetectorOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=model_path),
            min_detection_confidence=0.3,
        )
        detector = mp.tasks.vision.FaceDetector.create_from_options(options)
        _face_detectors[variant] = detector
        logger.info(f"MediaPipe FaceDetector ({variant}) initialized")
        return detector
    except Exception as e:
        logger.warning(f"MediaPipe init failed ({variant}), Haar fallback: {e}")
        _face_detectors[variant] = False
        return None


# ---------------------------------------------------------------------------
# Single-frame detection
# ---------------------------------------------------------------------------


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


def _merge_nms(faces: List[dict], iou_thr: float = _NMS_IOU) -> List[dict]:
    """Greedy NMS across detector variants: keep the higher-confidence box of
    any overlapping pair (the same face seen by both models is one face)."""
    kept: List[dict] = []
    for f in sorted(faces, key=lambda f: -f.get("confidence", 0)):
        if all(_iou(f, k) < iou_thr for k in kept):
            kept.append(f)
    return kept


def detect_faces(frame, video_w: int, video_h: int) -> List[dict]:
    """Detect all faces in a BGR frame. Returns list of {x, y, w, h, confidence}.

    Runs every configured BlazeFace variant (short + full range by default) and
    NMS-merges; falls back to Haar only when no variant initialized.
    """
    faces: List[dict] = []
    any_detector = False
    for variant in _face_variants():
        detector = _get_face_detector(variant)
        if not detector:
            continue
        any_detector = True
        for f in _detect_faces_mediapipe(detector, frame, video_w, video_h):
            f["det_src"] = variant
            faces.append(f)
    if not any_detector:
        return _detect_faces_haar(frame, video_w, video_h)
    return _merge_nms(faces)


def _detect_faces_mediapipe(detector, frame, video_w, video_h) -> List[dict]:
    """Detect faces using MediaPipe Tasks API."""
    import mediapipe as mp

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    result = detector.detect(mp_image)

    faces = []
    for det in result.detections:
        bb = det.bounding_box
        cx = (bb.origin_x + bb.width / 2) / video_w
        cy = (bb.origin_y + bb.height / 2) / video_h
        faces.append(
            {
                "x": max(0.0, min(1.0, cx)),
                "y": max(0.0, min(1.0, cy)),
                "w": bb.width / video_w,
                "h": bb.height / video_h,
                "confidence": det.categories[0].score if det.categories else 0.5,
            }
        )
    return faces


def _detect_faces_haar(frame, video_w, video_h) -> List[dict]:
    """Fallback: Haar cascade face detection."""
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    cascade = cv2.CascadeClassifier(cascade_path)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    rects = cascade.detectMultiScale(
        gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30)
    )
    return [
        {
            "x": (fx + fw / 2) / video_w,
            "y": (fy + fh / 2) / video_h,
            "w": fw / video_w,
            "h": fh / video_h,
            "confidence": min(1.0, (fw * fh) / (video_w * video_h) * 20),
        }
        for fx, fy, fw, fh in rects
    ]


def _ensure_object_model():
    """Download the person/object detection model if not cached."""
    global _OBJECT_MODEL_PATH
    if _OBJECT_MODEL_PATH and os.path.exists(_OBJECT_MODEL_PATH):
        return _OBJECT_MODEL_PATH
    cache_dir = os.path.join(tempfile.gettempdir(), "mediapipe_models")
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, "efficientdet_lite0.tflite")
    if not os.path.exists(path):
        logger.info(f"Downloading MediaPipe object model to {path}...")
        urllib.request.urlretrieve(_OBJECT_MODEL_URL, path)
    _OBJECT_MODEL_PATH = path
    return path


def _get_object_detector():
    """Lazy-init MediaPipe ObjectDetector limited to the 'person' class."""
    global _object_detector
    if _object_detector is not None:
        return _object_detector or None  # False (cached failure) → None
    try:
        import mediapipe as mp

        model_path = _ensure_object_model()
        options = mp.tasks.vision.ObjectDetectorOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=model_path),
            score_threshold=0.3,
            category_allowlist=["person"],
        )
        _object_detector = mp.tasks.vision.ObjectDetector.create_from_options(options)
        logger.info("MediaPipe ObjectDetector initialized")
        return _object_detector
    except Exception as e:
        logger.warning(f"MediaPipe ObjectDetector init failed: {e}")
        _object_detector = False  # cache failure to avoid per-frame retries
        return None


def detection_backend() -> dict:
    """Which detector backends actually initialized on this host.

    MediaPipe silently degrading to Haar (missing GL libs) and AV1 sources
    decoding zero frames have both shipped garbage while jobs "completed" —
    the eval's perception block turns either into a visible fail instead of
    leaving downstream layers to be blamed.
    """
    variants = [v for v in _face_variants() if _get_face_detector(v)]
    return {
        "face_backend": "mediapipe" if variants else "haar",
        "face_variants": variants,
        "person_backend": "efficientdet" if _get_object_detector() else "none",
    }


def detect_persons(frame, video_w: int, video_h: int) -> List[dict]:
    """Detect people (bodies) in a BGR frame. Returns list of {x, y, w, h, confidence}.

    Complements face detection: finds subjects with no visible frontal face.
    """
    detector = _get_object_detector()
    if not detector:
        return []
    import mediapipe as mp

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    result = detector.detect(mp_image)

    persons = []
    for det in result.detections:
        bb = det.bounding_box
        cx = (bb.origin_x + bb.width / 2) / video_w
        cy = (bb.origin_y + bb.height / 2) / video_h
        persons.append(
            {
                "x": max(0.0, min(1.0, cx)),
                "y": max(0.0, min(1.0, cy)),
                "w": bb.width / video_w,
                "h": bb.height / video_h,
                "confidence": det.categories[0].score if det.categories else 0.5,
            }
        )
    return persons


def scan_video_faces(video_path: str, sample_fps: float = 1.0) -> List[dict]:
    """Scan video at sample_fps, detect faces per frame.

    Returns list of {"time_sec": float, "faces": [...]}.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.warning(f"MediaPipe: failed to open {video_path}")
        return []

    video_fps = cap.get(cv2.CAP_PROP_FPS) or 30
    video_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    video_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    step = max(1, int(video_fps / sample_fps))

    frames_data = []
    idx = 0
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if idx % step == 0:
                faces = detect_faces(frame, video_w, video_h)
                frames_data.append({"time_sec": idx / video_fps, "faces": faces})
            idx += 1
    finally:
        cap.release()

    total_det = sum(len(f["faces"]) for f in frames_data)
    logger.info(f"MediaPipe scan: {len(frames_data)} frames, {total_det} detections")
    return frames_data


def scan_video_detections(
    video_path: str, sample_fps: float = 4.0, active_area: Optional[dict] = None
) -> List[dict]:
    """Scan once, running BOTH face and person detection per sampled frame.

    Returns list of {"time_sec", "faces": [...], "persons": [...]}. Single decode
    pass so adding persons doesn't double the video read.

    `active_area` (reframe_active_area fractions) trims baked-in letterbox bars
    off each frame BEFORE inference — every returned coordinate is then
    normalized to the real picture, and detectors see proportionally larger
    subjects. ``None`` = full frame (today's behavior).
    """
    from reframe_active_area import slice_frame

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.warning(f"MediaPipe: failed to open {video_path}")
        return []

    video_fps = cap.get(cv2.CAP_PROP_FPS) or 30
    step = max(1, int(video_fps / sample_fps))

    frames_data = []
    idx = 0
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if idx % step == 0:
                frame = slice_frame(frame, active_area)
                video_h, video_w = frame.shape[:2]
                faces = detect_faces(frame, video_w, video_h)
                # Mouth-aspect-ratio on EVERY detected face: single-face shots
                # need MAR too (talking-head vs static-poster evidence, and the
                # single-face speaker pin), not just ≥2-face ASD comparisons.
                if faces:
                    from active_speaker import mouth_aspect_ratio

                    for f in faces:
                        f["mouth"] = mouth_aspect_ratio(frame, f)
                        f["hist"] = _face_hist(frame, f, video_w, video_h)
                frames_data.append(
                    {
                        "time_sec": idx / video_fps,
                        "faces": faces,
                        "persons": detect_persons(frame, video_w, video_h),
                    }
                )
            idx += 1
    finally:
        cap.release()

    nf = sum(len(f["faces"]) for f in frames_data)
    np_ = sum(len(f["persons"]) for f in frames_data)
    logger.info(f"MediaPipe scan: {len(frames_data)} frames, {nf} faces, {np_} persons")
    return frames_data


# ---------------------------------------------------------------------------
# Face tracker
# ---------------------------------------------------------------------------
# v2 (default): gap-tolerant global-greedy matching on IoU + size-normalized
# center distance (+ appearance-histogram tiebreak), with a hard reset at scene
# cuts. Fixes the v1 failure that fragmented every subject into sub-threshold
# track shards: v1 matched only against the immediately previous sample, so a
# single missed detection minted a new track_id, and identities silently leaked
# across cuts onto different people.
_GAP_SEC = 1.0  # how long an unmatched track survives on its last box
_COST_MAX = 0.7  # (track, detection) pairs above this never link
_HIST_WEIGHT = 0.2  # appearance term (Bhattacharyya) when both sides have one


def _face_hist(frame, f: dict, video_w: int, video_h: int):
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


def _hist_dist(a, b) -> float:
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


def _track_faces_v2(frames_data: List[dict], cuts: List[float]) -> List[dict]:
    # Sampling interval from the data itself (fps-independent; tolerates gaps).
    times = [fd["time_sec"] for fd in frames_data]
    deltas = sorted(b - a for a, b in zip(times, times[1:]) if b > a)
    dt = deltas[len(deltas) // 2] if deltas else 1.0
    max_misses = max(1, round(_GAP_SEC / dt))
    # A subject/camera faster than half a frame-width per second reads as a
    # different subject; per-sample ceiling scales with the sampling interval.
    max_step = 0.5 * dt

    next_id = 0
    live: List[dict] = []  # {tid, x, y, w, h, hist, misses}
    cut_i = 0
    prev_t = None
    result = []

    for fd in frames_data:
        t = fd["time_sec"]
        # Hard reset at scene cuts: identity never crosses a cut.
        while cut_i < len(cuts) and cuts[cut_i] <= t:
            if prev_t is None or cuts[cut_i] > prev_t:
                live = []
            cut_i += 1
        prev_t = t

        faces = fd["faces"]
        # Global greedy assignment over all (track, detection) pairs by cost.
        pairs = []
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
        used_t, used_f = set(), set()
        assign = {}
        for cost, ti, fi in pairs:
            if ti in used_t or fi in used_f:
                continue
            used_t.add(ti)
            used_f.add(fi)
            assign[fi] = ti

        frame_tracks = []
        new_live = []
        for fi, f in enumerate(faces):
            if fi in assign:
                tr = live[assign[fi]]
                tid = tr["tid"]
            else:
                tid = next_id
                next_id += 1
            frame_tracks.append(
                {
                    "track_id": tid,
                    "x": f["x"],
                    "y": f["y"],
                    "w": f.get("w", 0.0),
                    "h": f.get("h", 0.0),
                    "confidence": f.get("confidence", 0.5),
                    "mouth": f.get("mouth"),  # MAR for ASD (None if unknown)
                }
            )
            new_live.append(
                {
                    "tid": tid,
                    "x": f["x"],
                    "y": f["y"],
                    "w": f.get("w", 0.0),
                    "h": f.get("h", 0.0),
                    "hist": f.get("hist"),
                    "misses": 0,
                }
            )
        # Unmatched tracks survive on their last box for _GAP_SEC — one missed
        # detection no longer mints a new identity. Gap frames are NOT emitted
        # (frac stays honest); only the id is preserved for re-linking.
        for ti, tr in enumerate(live):
            if ti not in used_t:
                tr["misses"] += 1
                if tr["misses"] <= max_misses:
                    new_live.append(tr)
        live = new_live
        result.append({"time_sec": t, "tracks": frame_tracks})

    logger.info(
        f"Tracker(v2): {next_id} unique tracks across {len(result)} frames "
        f"(dt={dt:.2f}s, gap={max_misses} misses)"
    )
    return result


def _track_faces_v1(frames_data: List[dict], max_distance: float) -> List[dict]:
    """Legacy tracker: greedy nearest-neighbor vs the previous sample only."""
    next_id = 0
    prev_tracks = []
    result = []

    for fd in frames_data:
        matched = _match_tracks(prev_tracks, fd["faces"], max_distance)
        frame_tracks, new_prev = [], []
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
                    "mouth": face.get("mouth"),  # MAR for ASD (None if unknown)
                }
            )
            new_prev.append({"track_id": tid, "x": face["x"], "y": face["y"]})
        prev_tracks = new_prev
        result.append({"time_sec": fd["time_sec"], "tracks": frame_tracks})

    logger.info(f"Tracker: {next_id} unique tracks across {len(result)} frames")
    return result


def _match_tracks(prev: List[dict], faces: List[dict], max_dist: float) -> List[tuple]:
    """Match faces to previous tracks by nearest position (v1)."""
    if not prev:
        return [(f, None) for f in faces]
    used = set()
    matched = []
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


# ---------------------------------------------------------------------------
# Scene-to-track merging
# ---------------------------------------------------------------------------


def merge_scenes_with_tracks(
    scenes: List[dict],
    tracked_frames: List[dict],
    video_duration: float,
) -> List[dict]:
    """Merge Gemini scene hints with MediaPipe tracked positions → focal points."""
    focal_points = []
    frame_times = [f["time_sec"] for f in tracked_frames]
    for scene in scenes:
        start = scene.get("start_sec", 0)
        end = scene.get("end_sec", video_duration)
        hint = scene.get("active_subject", "center")
        scene_type = scene.get("scene_type", "general")
        desc = scene.get("description", "")

        lo = bisect.bisect_left(frame_times, start)
        hi = bisect.bisect_right(frame_times, end)
        scene_frames = tracked_frames[lo:hi]
        if not scene_frames:
            focal_points.append(_center_point(start, desc))
            continue

        for sf in scene_frames:
            if not sf["tracks"]:
                focal_points.append(_center_point(sf["time_sec"], desc))
                continue
            target = _pick_track(sf["tracks"], hint, scene_type)
            focal_points.append(
                {
                    "time_sec": sf["time_sec"],
                    "x": target["x"],
                    "y": target["y"],
                    "confidence": target["confidence"],
                    "description": desc,
                }
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

    # "Track A" → track_id matching the Nth most-visible track
    # (Track A = most visible, B = second, etc.)
    import re

    track_match = re.search(r"track\s+([a-z])", h)
    if track_match:
        idx = ord(track_match.group(1)) - ord("a")
        # Sort by track_id frequency isn't available here, but tracks
        # in the current frame are ordered. Pick by index if valid.
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
