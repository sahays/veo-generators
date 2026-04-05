"""MediaPipe-based face detection and tracking for smart reframing.

Uses the MediaPipe Tasks API (v0.10+) with downloaded model files.
Falls back to OpenCV Haar cascade if MediaPipe fails to initialize.
"""

import logging
import os
import tempfile
import urllib.request
from typing import List, Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Model URLs (Google's hosted models)
_FACE_MODEL_URL = "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/latest/blaze_face_short_range.tflite"
_FACE_MODEL_PATH = None
_face_detector = None


def _ensure_model():
    """Download face detection model if not cached."""
    global _FACE_MODEL_PATH
    if _FACE_MODEL_PATH and os.path.exists(_FACE_MODEL_PATH):
        return _FACE_MODEL_PATH
    cache_dir = os.path.join(tempfile.gettempdir(), "mediapipe_models")
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, "blaze_face_short_range.tflite")
    if not os.path.exists(path):
        logger.info(f"Downloading MediaPipe face model to {path}...")
        urllib.request.urlretrieve(_FACE_MODEL_URL, path)
    _FACE_MODEL_PATH = path
    return path


def _get_face_detector():
    """Lazy-init MediaPipe FaceDetector."""
    global _face_detector
    if _face_detector is not None:
        return _face_detector
    try:
        import mediapipe as mp

        model_path = _ensure_model()
        options = mp.tasks.vision.FaceDetectorOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=model_path),
            min_detection_confidence=0.3,
        )
        _face_detector = mp.tasks.vision.FaceDetector.create_from_options(options)
        logger.info("MediaPipe FaceDetector initialized")
        return _face_detector
    except Exception as e:
        logger.warning(f"MediaPipe init failed, will use Haar cascade: {e}")
        return None


# ---------------------------------------------------------------------------
# Single-frame detection
# ---------------------------------------------------------------------------


def detect_faces(frame, video_w: int, video_h: int) -> List[dict]:
    """Detect all faces in a BGR frame. Returns list of {x, y, w, h, confidence}."""
    detector = _get_face_detector()
    if detector:
        return _detect_faces_mediapipe(detector, frame, video_w, video_h)
    return _detect_faces_haar(frame, video_w, video_h)


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


def detect_motion(prev_frame, curr_frame, video_w: int, video_h: int) -> Optional[dict]:
    """Detect motion between two frames via frame differencing."""
    if prev_frame is None:
        return None
    gray1 = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
    gray2 = cv2.cvtColor(curr_frame, cv2.COLOR_BGR2GRAY)
    diff = cv2.absdiff(gray1, gray2)
    _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
    thresh = cv2.dilate(thresh, np.ones((5, 5), np.uint8), iterations=2)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    largest = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(largest)
    if area < video_w * video_h * 0.005:
        return None
    M = cv2.moments(largest)
    if M["m00"] == 0:
        return None
    return {
        "x": (M["m10"] / M["m00"]) / video_w,
        "y": (M["m01"] / M["m00"]) / video_h,
        "confidence": min(1.0, area / (video_w * video_h) * 10),
    }


# ---------------------------------------------------------------------------
# Full-video scan
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Simple position-based tracker
# ---------------------------------------------------------------------------


def track_faces(frames_data: List[dict], max_distance: float = 0.15) -> List[dict]:
    """Assign persistent track IDs across frames by position proximity.

    Returns list of {"time_sec", "tracks": [{"track_id", "x", "y", "confidence"}]}.
    """
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
                    "confidence": face.get("confidence", 0.5),
                }
            )
            new_prev.append({"track_id": tid, "x": face["x"], "y": face["y"]})
        prev_tracks = new_prev
        result.append({"time_sec": fd["time_sec"], "tracks": frame_tracks})

    logger.info(f"Tracker: {next_id} unique tracks across {len(result)} frames")
    return result


def _match_tracks(prev: List[dict], faces: List[dict], max_dist: float) -> List[tuple]:
    """Match faces to previous tracks by nearest position."""
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
    for scene in scenes:
        start = scene.get("start_sec", 0)
        end = scene.get("end_sec", video_duration)
        hint = scene.get("active_subject", "center")
        scene_type = scene.get("scene_type", "general")
        desc = scene.get("description", "")

        scene_frames = [f for f in tracked_frames if start <= f["time_sec"] <= end]
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
