"""MediaPipe-based face detection and tracking for smart reframing.

Uses the MediaPipe Tasks API (v0.10+) with downloaded model files.
Falls back to OpenCV Haar cascade if MediaPipe fails to initialize.
"""

import logging
import os
import tempfile
import urllib.request
from typing import Any, List, Optional

import cv2
from mediapipe_tracking import (
    _COST_MAX,
    _GAP_SEC,
    _HIST_WEIGHT,
    _center_point,
    _face_hist,
    _hist_dist,
    _iou,
    _match_tracks,
    _pick_track,
    _track_faces_v1,
    _track_faces_v2,
    merge_scenes_with_tracks,
    track_faces,
)

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


def _ensure_model(variant: str = "short") -> str:
    """Download a face detection model variant if not cached."""
    cache_dir = os.path.join(tempfile.gettempdir(), "mediapipe_models")
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, f"blaze_face_{variant}_range.tflite")
    if not os.path.exists(path):
        logger.info(
            f"Downloading MediaPipe face model ({variant}) to {path}...",
            extra={
                "who": "mediapipe_detection",
                "where": "_ensure_model",
                "what": variant,
                "why": "missing_model",
                "how": "urlretrieve",
            },
        )
        urllib.request.urlretrieve(_FACE_MODEL_URLS[variant], path)
    return path


def _get_face_detector(variant: str = "short") -> Any:
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
        logger.info(
            f"MediaPipe FaceDetector ({variant}) initialized",
            extra={
                "who": "mediapipe_detection",
                "where": "_get_face_detector",
                "what": variant,
                "why": "detector_ready",
                "how": "mediapipe",
            },
        )
        return detector
    except Exception as e:
        logger.warning(
            f"MediaPipe init failed ({variant}), Haar fallback: {e}",
            extra={
                "who": "mediapipe_detection",
                "where": "_get_face_detector",
                "what": str(e),
                "why": "init_failed",
                "how": "haar_fallback",
            },
        )
        _face_detectors[variant] = False
        return None


def _merge_nms(faces: List[dict], iou_thr: float = _NMS_IOU) -> List[dict]:
    """Greedy NMS across detector variants: keep the higher-confidence box of
    any overlapping pair (the same face seen by both models is one face)."""
    kept: List[dict] = []
    for f in sorted(faces, key=lambda f: -f.get("confidence", 0)):
        if all(_iou(f, k) < iou_thr for k in kept):
            kept.append(f)
    return kept


def detect_faces(frame: Any, video_w: int, video_h: int) -> List[dict]:
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


def _detect_faces_mediapipe(
    detector: Any, frame: Any, video_w: int, video_h: int
) -> List[dict]:
    """Detect faces using MediaPipe Tasks API."""
    import mediapipe as mp

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    result = detector.detect(mp_image)

    faces: List[dict] = []
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


def _detect_faces_haar(frame: Any, video_w: int, video_h: int) -> List[dict]:
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


def _ensure_object_model() -> str:
    """Download the person/object detection model if not cached."""
    global _OBJECT_MODEL_PATH
    if _OBJECT_MODEL_PATH and os.path.exists(_OBJECT_MODEL_PATH):
        return _OBJECT_MODEL_PATH
    cache_dir = os.path.join(tempfile.gettempdir(), "mediapipe_models")
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, "efficientdet_lite0.tflite")
    if not os.path.exists(path):
        logger.info(
            f"Downloading MediaPipe object model to {path}...",
            extra={
                "who": "mediapipe_detection",
                "where": "_ensure_object_model",
                "what": path,
                "why": "missing_model",
                "how": "urlretrieve",
            },
        )
        urllib.request.urlretrieve(_OBJECT_MODEL_URL, path)
    _OBJECT_MODEL_PATH = path
    return path


def _get_object_detector() -> Any:
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
        logger.info(
            "MediaPipe ObjectDetector initialized",
            extra={
                "who": "mediapipe_detection",
                "where": "_get_object_detector",
                "what": "initialized",
                "why": "detector_ready",
                "how": "mediapipe",
            },
        )
        return _object_detector
    except Exception as e:
        logger.warning(
            f"MediaPipe ObjectDetector init failed: {e}",
            extra={
                "who": "mediapipe_detection",
                "where": "_get_object_detector",
                "what": str(e),
                "why": "init_failed",
                "how": "disable_person_detector",
            },
        )
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


def detect_persons(frame: Any, video_w: int, video_h: int) -> List[dict]:
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

    persons: List[dict] = []
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
        logger.warning(
            f"MediaPipe: failed to open {video_path}",
            extra={
                "who": "mediapipe_detection",
                "where": "scan_video_faces",
                "what": video_path,
                "why": "open_failed",
                "how": "return_empty",
            },
        )
        return []

    video_fps = cap.get(cv2.CAP_PROP_FPS) or 30
    video_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    video_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    step = max(1, int(video_fps / sample_fps))

    frames_data: List[dict] = []
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
    logger.info(
        f"MediaPipe scan: {len(frames_data)} frames, {total_det} detections",
        extra={
            "who": "mediapipe_detection",
            "where": "scan_video_faces",
            "what": f"{total_det}_detections",
            "why": "scan_complete",
            "how": "mediapipe",
        },
    )
    return frames_data


def _sample_frame_detections(
    frame: Any, active_area: Optional[dict], time_sec: float
) -> dict:
    from reframe_active_area import slice_frame

    frame = slice_frame(frame, active_area)
    video_h, video_w = frame.shape[:2]
    faces = detect_faces(frame, video_w, video_h)
    if faces:
        from active_speaker import mouth_aspect_ratio

        for f in faces:
            f["mouth"] = mouth_aspect_ratio(frame, f)
            f["hist"] = _face_hist(frame, f, video_w, video_h)
    return {
        "time_sec": time_sec,
        "faces": faces,
        "persons": detect_persons(frame, video_w, video_h),
    }


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
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.warning(
            f"MediaPipe: failed to open {video_path}",
            extra={
                "who": "mediapipe_detection",
                "where": "scan_video_detections",
                "what": video_path,
                "why": "open_failed",
                "how": "return_empty",
            },
        )
        return []

    video_fps = cap.get(cv2.CAP_PROP_FPS) or 30
    step = max(1, int(video_fps / sample_fps))

    frames_data: List[dict] = []
    idx = 0
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if idx % step == 0:
                frames_data.append(
                    _sample_frame_detections(frame, active_area, idx / video_fps)
                )
            idx += 1
    finally:
        cap.release()

    nf = sum(len(f["faces"]) for f in frames_data)
    np_ = sum(len(f["persons"]) for f in frames_data)
    logger.info(
        f"MediaPipe scan: {len(frames_data)} frames, {nf} faces, {np_} persons",
        extra={
            "who": "mediapipe_detection",
            "where": "scan_video_detections",
            "what": f"{nf}_faces_{np_}_persons",
            "why": "scan_complete",
            "how": "mediapipe",
        },
    )
    return frames_data


__all__ = [
    "_COST_MAX",
    "_GAP_SEC",
    "_HIST_WEIGHT",
    "_center_point",
    "_face_hist",
    "_hist_dist",
    "_iou",
    "_match_tracks",
    "_merge_nms",
    "_pick_track",
    "_track_faces_v1",
    "_track_faces_v2",
    "detect_faces",
    "detect_persons",
    "detection_backend",
    "merge_scenes_with_tracks",
    "scan_video_detections",
    "scan_video_faces",
    "track_faces",
]
