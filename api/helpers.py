import asyncio
import logging
from typing import Optional

from fastapi import HTTPException

import deps
from models import Project, Scene

# Re-export from split modules so existing imports keep working
from url_signing import (  # noqa: F401
    sign_record_urls,
    sign_production_urls,
    list_video_upload_sources,
    list_image_upload_sources,
    list_completed_production_sources,
)
from cost_tracking import (  # noqa: F401
    accumulate_cost,
    accumulate_image_cost,
    accumulate_veo_cost,
)

logger = logging.getLogger(__name__)


# --- Shared Utilities ---


def require_firestore():
    """Raise 503 if Firestore service is not initialized."""
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")


def get_or_404(get_fn, record_id: str, name: str = "Record"):
    """Fetch a record by ID or raise 404 if not found."""
    record = get_fn(record_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return record


# --- Gemini API ---


async def gemini_call_with_retry(
    client,
    model: str,
    contents: list,
    config,
    max_retries: int = 4,
    initial_backoff: int = 2,
):
    """Call Gemini with exponential backoff on rate limits."""
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return client.models.generate_content(
                model=model, contents=contents, config=config
            )
        except Exception as e:
            last_error = e
            err_str = str(e)
            is_rate_limit = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str
            if is_rate_limit and attempt < max_retries:
                wait = initial_backoff * (2**attempt)
                logger.warning(
                    f"Rate-limited (attempt {attempt + 1}/{max_retries + 1}), "
                    f"retrying in {wait}s: {err_str[:200]}"
                )
                await asyncio.sleep(wait)
            else:
                raise
    raise last_error  # type: ignore[misc]


# --- Prompt Building ---


def parse_timestamp(ts: str) -> float:
    """Parse '00:05' or '5' to seconds."""
    if ":" in ts:
        parts = ts.split(":")
        return int(parts[0]) * 60 + float(parts[1])
    return float(ts)


def orientation_directive(orientation: Optional[str]) -> str:
    """Return a text directive reinforcing the desired aspect ratio."""
    if orientation == "9:16":
        return "Aspect ratio: 9:16 (portrait/vertical)."
    if orientation == "16:9":
        return "Aspect ratio: 16:9 (landscape/horizontal)."
    if orientation:
        return f"Aspect ratio: {orientation}."
    return ""


def build_flat_image_prompt(data: dict) -> str:
    """Build a flat text prompt for image generation."""
    parts = []
    od = orientation_directive(data.get("orientation"))
    if od:
        parts.append(od)
    gs = data.get("global_style")
    if gs:
        parts.append(
            f"Style: {gs.get('look', '')}. Mood: {gs.get('mood', '')}. "
            f"Colors: {gs.get('color_grading', '')}. "
            f"Lighting: {gs.get('lighting_style', '')}."
        )
    cont = data.get("continuity")
    if cont and cont.get("characters"):
        char_descs = [
            f"{c['id']}: {c['description']}, wearing {c.get('wardrobe', '')}"
            for c in cont["characters"]
        ]
        parts.append(f"Characters: {'; '.join(char_descs)}.")
    if cont and cont.get("setting_notes"):
        parts.append(f"Setting: {cont['setting_notes']}.")
    parts.append(data.get("visual_description", ""))
    return " ".join(parts)


def build_flat_video_prompt(data: dict) -> str:
    """Build a flat text prompt for video generation."""
    parts = _build_video_base_parts(data)
    _append_transitions(parts, data)
    _append_narration(parts, data)
    _append_music(parts, data)
    return " ".join(parts)


def _build_video_base_parts(data: dict) -> list[str]:
    """Build the core video prompt parts (duration, style, characters)."""
    parts = [f"{data.get('duration', 8)}-second video clip."]
    od = orientation_directive(data.get("orientation"))
    if od:
        parts.append(od)
    md = data.get("metadata", {})
    for key, label in [
        ("camera_angle", "Camera angle"),
        ("camera_movement", "Camera movement"),
        ("cinematic_style", "Cinematic style"),
    ]:
        if md.get(key):
            parts.append(f"{label}: {md[key]}.")
    gs = data.get("global_style")
    pace = md.get("pace") or (gs.get("pace") if gs else None)
    if pace:
        parts.append(f"Pace: {pace}.")
    if gs:
        parts.append(
            f"Style: {gs.get('look', '')}. Mood: {gs.get('mood', '')}. "
            f"Colors: {gs.get('color_grading', '')}. "
            f"Lighting: {gs.get('lighting_style', '')}."
        )
    cont = data.get("continuity")
    if cont and cont.get("characters"):
        char_descs = [
            f"{c['id']}: {c['description']}, wearing {c.get('wardrobe', '')}"
            for c in cont["characters"]
        ]
        parts.append(f"Characters: {'; '.join(char_descs)}.")
    if cont and cont.get("setting_notes"):
        parts.append(f"Setting: {cont['setting_notes']}.")
    parts.append(data.get("visual_description", ""))
    return parts


def _append_transitions(parts: list[str], data: dict):
    """Append transition directives to prompt parts."""
    if data.get("enter_transition"):
        parts.append(data["enter_transition"])
    if data.get("exit_transition"):
        parts.append(data["exit_transition"])
    if data.get("music_transition"):
        parts.append(f"Music transition: {data['music_transition']}")


def _append_narration(parts: list[str], data: dict):
    """Append narration directive if enabled."""
    if data.get("narration_enabled"):
        narration = data.get("narration")
        if narration:
            parts.append(f'Voice-over narration: "{narration}"')


def _append_music(parts: list[str], data: dict):
    """Append music directive if enabled."""
    if not data.get("music_enabled"):
        return
    music = data.get("music_description")
    if not music:
        gs = data.get("global_style")
        if gs and gs.get("soundtrack_style"):
            music = gs["soundtrack_style"]
    if music:
        parts.append(f"Background music: {music}.")


SUPPORTED_DURATIONS = [4, 6, 8]


def build_prompt_data(scene: Scene, project: Project) -> dict:
    """Build structured prompt data for a scene."""
    try:
        start = parse_timestamp(scene.timestamp_start)
        end = parse_timestamp(scene.timestamp_end)
        raw = int(end - start)
        duration = min(SUPPORTED_DURATIONS, key=lambda d: abs(d - raw))
    except (ValueError, IndexError):
        duration = 8

    data = {
        "visual_description": scene.visual_description,
        "metadata": scene.metadata.dict() if scene.metadata else {},
        "global_style": (project.global_style.dict() if project.global_style else None),
        "continuity": (project.continuity.dict() if project.continuity else None),
        "duration": duration,
        "orientation": project.orientation,
        "narration": scene.narration,
        "narration_enabled": scene.narration_enabled,
        "music_description": scene.music_description,
        "music_enabled": scene.music_enabled,
        "enter_transition": scene.enter_transition,
        "exit_transition": scene.exit_transition,
        "music_transition": scene.music_transition,
    }
    data["image_prompt"] = build_flat_image_prompt(data)
    data["video_prompt"] = build_flat_video_prompt(data)
    return data
