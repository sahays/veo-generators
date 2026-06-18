"""Active-speaker detection signal — mouth movement via MediaPipe FaceLandmarker.

Visual ASD: the face whose mouth is moving is the one speaking. This module only
extracts the per-face *mouth-aspect-ratio* (lip gap / mouth width); the decision
of who is the active speaker (variance over time) lives in `reframe_plan`
(pure logic). Degrades to None everywhere if the landmarker can't load.
"""

import logging
import os
import tempfile
import urllib.request
from typing import Optional

import cv2

logger = logging.getLogger(__name__)

_LANDMARKER_URL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
_LANDMARKER_PATH = None
_landmarker = None  # None = not tried; False = init failed (cached)

# MediaPipe FaceMesh lip landmark indices.
_UPPER_LIP, _LOWER_LIP = 13, 14  # inner top / bottom of lips
_LEFT_CORNER, _RIGHT_CORNER = 78, 308  # mouth corners


def _ensure_landmarker_model():
    global _LANDMARKER_PATH
    if _LANDMARKER_PATH and os.path.exists(_LANDMARKER_PATH):
        return _LANDMARKER_PATH
    cache_dir = os.path.join(tempfile.gettempdir(), "mediapipe_models")
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, "face_landmarker.task")
    if not os.path.exists(path):
        logger.info(f"Downloading MediaPipe face landmarker to {path}...")
        urllib.request.urlretrieve(_LANDMARKER_URL, path)
    _LANDMARKER_PATH = path
    return path


def _get_landmarker():
    global _landmarker
    if _landmarker is not None:
        return _landmarker or None
    try:
        import mediapipe as mp

        model_path = _ensure_landmarker_model()
        options = mp.tasks.vision.FaceLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=model_path),
            num_faces=1,
        )
        _landmarker = mp.tasks.vision.FaceLandmarker.create_from_options(options)
        logger.info("MediaPipe FaceLandmarker initialized")
        return _landmarker
    except Exception as e:
        logger.warning(f"FaceLandmarker init failed (ASD disabled): {e}")
        _landmarker = False
        return None


def mouth_aspect_ratio(frame, face: dict) -> Optional[float]:
    """Mouth-aspect-ratio (lip gap / mouth width) for one detected face.

    Scale-invariant, so it can be compared across faces and over time. Returns
    None if landmarks aren't found. `face` has fractional center x/y + dims w/h.
    """
    lm = _get_landmarker()
    if not lm:
        return None
    h, w = frame.shape[:2]
    cx, cy, fw, fh = face["x"] * w, face["y"] * h, face["w"] * w, face["h"] * h
    pad = 0.35
    x0 = int(max(0, cx - fw * (0.5 + pad)))
    x1 = int(min(w, cx + fw * (0.5 + pad)))
    y0 = int(max(0, cy - fh * (0.5 + pad)))
    y1 = int(min(h, cy + fh * (0.5 + pad)))
    crop = frame[y0:y1, x0:x1]
    if crop.shape[0] < 16 or crop.shape[1] < 16:
        return None
    try:
        import mediapipe as mp

        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = lm.detect(img)
        if not result.face_landmarks:
            return None
        p = result.face_landmarks[0]
        gap = abs(p[_UPPER_LIP].y - p[_LOWER_LIP].y)
        width = abs(p[_LEFT_CORNER].x - p[_RIGHT_CORNER].x)
        if width <= 1e-6:
            return None
        return gap / width
    except Exception as e:  # noqa: BLE001 — ASD is best-effort
        logger.debug(f"MAR failed: {e}")
        return None
