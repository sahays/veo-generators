"""OpenCV-based focal point validation for the reframe pipeline.

Validates and corrects Gemini's focal point coordinates by running actual
detection on sampled video frames. Two strategies:
- Default: face/person detection (best for interviews, entertainment)
- Sports mode: motion detection via frame differencing (best for fast action)
"""

import logging
from typing import List

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Face detection model (ships with OpenCV)
_face_cascade = None


def _get_face_detector():
    global _face_cascade
    if _face_cascade is None:
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        _face_cascade = cv2.CascadeClassifier(cascade_path)
    return _face_cascade


def _read_frame_at(cap: cv2.VideoCapture, time_sec: float):
    """Seek to a timestamp and read a frame. Returns (success, frame)."""
    cap.set(cv2.CAP_PROP_POS_MSEC, time_sec * 1000)
    ret, frame = cap.read()
    return ret, frame


def _detect_faces(frame, video_w: int, video_h: int) -> tuple:
    """Detect faces in a frame. Returns (x_frac, y_frac, confidence) or None."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    detector = _get_face_detector()
    faces = detector.detectMultiScale(
        gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30)
    )
    if len(faces) == 0:
        return None

    # Pick the largest face (most likely the main subject)
    largest = max(faces, key=lambda f: f[2] * f[3])
    fx, fy, fw, fh = largest
    center_x = (fx + fw / 2) / video_w
    center_y = (fy + fh / 2) / video_h
    # Confidence based on face size relative to frame
    confidence = min(1.0, (fw * fh) / (video_w * video_h) * 20)
    return center_x, center_y, confidence


def _detect_motion(prev_frame, curr_frame, video_w: int, video_h: int) -> tuple:
    """Detect motion between two frames. Returns (x_frac, y_frac, confidence) or None."""
    if prev_frame is None:
        return None

    # Convert to grayscale
    gray1 = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
    gray2 = cv2.cvtColor(curr_frame, cv2.COLOR_BGR2GRAY)

    # Frame difference
    diff = cv2.absdiff(gray1, gray2)
    _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)

    # Dilate to fill gaps
    kernel = np.ones((5, 5), np.uint8)
    thresh = cv2.dilate(thresh, kernel, iterations=2)

    # Find contours
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    # Find the largest motion region
    largest = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(largest)

    # Ignore tiny motion (noise)
    min_area = video_w * video_h * 0.005  # at least 0.5% of frame
    if area < min_area:
        return None

    # Centroid of the motion region
    M = cv2.moments(largest)
    if M["m00"] == 0:
        return None
    cx = M["m10"] / M["m00"]
    cy = M["m01"] / M["m00"]

    x_frac = cx / video_w
    y_frac = cy / video_h
    confidence = min(1.0, area / (video_w * video_h) * 10)
    return x_frac, y_frac, confidence


def validate_focal_points(
    video_path: str,
    focal_points: List[dict],
    video_w: int,
    video_h: int,
    sports_mode: bool = False,
    sample_interval: float = 2.0,
) -> List[dict]:
    """Validate and correct focal points using OpenCV detection.

    Args:
        video_path: Path to the source video file.
        focal_points: List of {time_sec, x, y, ...} from Gemini.
        video_w: Source video width in pixels.
        video_h: Source video height in pixels.
        sports_mode: If True, use motion detection instead of face detection.
        sample_interval: Only validate every N seconds (skip others for speed).

    Returns:
        Same list with x, y corrected where OpenCV detection succeeds.
    """
    if not focal_points:
        return focal_points

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.warning(f"OpenCV: failed to open {video_path}, skipping validation")
        return focal_points

    corrected = list(focal_points)  # shallow copy
    corrections = 0
    samples = 0
    prev_frame = None
    last_sampled_time = -sample_interval  # ensure first point is sampled

    try:
        for i, fp in enumerate(corrected):
            t = fp["time_sec"]

            # Only sample at intervals to keep it fast
            if t - last_sampled_time < sample_interval:
                continue
            last_sampled_time = t

            ret, frame = _read_frame_at(cap, t)
            if not ret or frame is None:
                continue

            samples += 1
            result = None

            if sports_mode:
                # Read a frame slightly before for comparison
                if prev_frame is None:
                    prev_t = max(0, t - 0.5)
                    ret2, prev_frame = _read_frame_at(cap, prev_t)
                    if not ret2:
                        prev_frame = None
                        continue
                    # Re-read current frame (seek moved)
                    ret, frame = _read_frame_at(cap, t)
                    if not ret:
                        continue

                result = _detect_motion(prev_frame, frame, video_w, video_h)
                prev_frame = frame.copy()
            else:
                result = _detect_faces(frame, video_w, video_h)

            if result is not None:
                det_x, det_y, det_conf = result
                orig_x = fp["x"]
                distance = abs(det_x - orig_x)

                # Only correct if detection is confident and significantly different
                if det_conf > 0.3 and distance > 0.05:
                    corrected[i] = {
                        **fp,
                        "x": det_x,
                        "y": det_y,
                        "confidence": det_conf,
                    }
                    corrections += 1
                    logger.info(
                        f"OpenCV corrected t={t:.1f}s: "
                        f"x={orig_x:.2f}→{det_x:.2f} "
                        f"({'motion' if sports_mode else 'face'}, conf={det_conf:.2f})"
                    )

        mode_str = "motion" if sports_mode else "face"
        logger.info(
            f"OpenCV validation: {samples} frames sampled, "
            f"{corrections} corrections ({mode_str} mode)"
        )

    finally:
        cap.release()

    return corrected
