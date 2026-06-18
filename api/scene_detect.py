"""Frame-accurate scene-cut detection via PySceneDetect.

Thin wrapper used by the reframe v2 pipeline to find hard cuts, which become the
segment boundaries the rest of the pipeline snaps to. Gemini labels *within*
these boundaries; it does not own them.
"""

import logging
from typing import List

logger = logging.getLogger(__name__)


def detect_cuts(
    video_path: str,
    threshold: float = 27.0,
    min_scene_len_frames: int = 15,
) -> List[float]:
    """Return interior cut timestamps (seconds), sorted, excluding 0 and end.

    An empty list means the whole video is a single scene. Falls back to an empty
    list (single segment) if PySceneDetect is unavailable or errors.
    """
    try:
        from scenedetect import ContentDetector, detect
    except ImportError:
        logger.warning("scenedetect not installed — treating video as one scene")
        return []

    try:
        scenes = detect(
            video_path,
            ContentDetector(threshold=threshold, min_scene_len=min_scene_len_frames),
        )
    except Exception as e:  # corrupt input, no frames, etc.
        logger.warning(f"scene detection failed ({e}) — treating video as one scene")
        return []

    # scenes: list of (start_timecode, end_timecode); each scene start after the
    # first is a cut boundary.
    cuts = sorted(s[0].seconds for s in scenes[1:])
    logger.info(f"Scene detection: {len(cuts)} cuts in {len(scenes)} scenes")
    return cuts
