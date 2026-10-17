import asyncio
import logging
from typing import Any, Callable, Optional

from fastapi import HTTPException

import deps
from models import Project, Scene
from prompt_templates import PHYSICAL_REALISM_DIRECTIVE

# Re-export from split modules so existing imports keep working
from url_signing import (  # noqa: F401
    sign_record_urls,
    sign_records_concurrently,
    sign_nested_list_uris,
    sign_production_urls,
    list_video_upload_sources,
    list_image_upload_sources,
    list_completed_production_sources,
)

logger = logging.getLogger(__name__)


# --- Shared Utilities ---


def require_firestore() -> None:
    """Raise 503 if Firestore service is not initialized."""
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")


def ensure_services_ready() -> None:
    """Ensure core persistence services are initialized (router-facing helper)."""
    require_firestore()


def get_or_404(
    get_fn: Callable[[str], Any], record_id: str, name: str = "Record"
) -> Any:
    """Fetch a record by ID or raise 404 if not found."""
    record = get_fn(record_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return record


def apply_indexed_uris(
    items: list[dict], incoming: list[dict], uri_field: str = "gcs_uri"
) -> list[dict]:
    """Apply client-captured `[{index, gcs_uri}]` entries onto `items[index][uri_field]`.

    Shared by endpoints that persist browser-captured frames into a record's
    nested list (thumbnail screenshots, key-moment frames). Mutates and returns
    `items`.
    """
    for entry in incoming:
        idx = entry.get("index")
        gcs_uri = entry.get("gcs_uri")
        if idx is not None and 0 <= idx < len(items) and gcs_uri:
            items[idx][uri_field] = gcs_uri
    return items


# --- Gemini API ---


async def sdk_call_with_retry(
    fn: Callable[..., Any],
    *args: Any,
    max_retries: int = 4,
    initial_backoff: int = 2,
    **kwargs: Any,
) -> Any:
    """Run a blocking SDK call in a worker thread with exponential backoff on 429s."""
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return await asyncio.to_thread(fn, *args, **kwargs)
        except Exception as e:
            last_error = e
            err_str = str(e)
            is_rate_limit = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str
            if is_rate_limit and attempt < max_retries:
                wait = initial_backoff * (2**attempt)
                logger.warning(
                    f"Rate-limited (attempt {attempt + 1}/{max_retries + 1}), retrying in {wait}s: {err_str[:200]}",
                    extra={
                        "who": "helpers",
                        "where": "sdk_call_with_retry",
                        "what": "rate_limit_backoff",
                        "why": err_str[:120],
                        "how": f"sleep_{wait}s",
                    },
                )
                await asyncio.sleep(wait)
            else:
                raise
    raise last_error  # type: ignore[misc]


async def gemini_call_with_retry(
    client: Any,
    model: str,
    contents: list,
    config: Any,
    max_retries: int = 4,
    initial_backoff: int = 2,
) -> Any:
    """Call Gemini with exponential backoff on rate limits."""
    return await sdk_call_with_retry(
        client.models.generate_content,
        model=model,
        contents=contents,
        config=config,
        max_retries=max_retries,
        initial_backoff=initial_backoff,
    )


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


def _append_continuity_parts(parts: list[str], cont: Optional[dict]) -> None:
    """Append character and setting continuity notes onto prompt parts."""
    if not cont:
        return
    if cont.get("characters"):
        char_descs = [
            f"{c['id']}: {c['description']}, wearing {c.get('wardrobe', '')}"
            for c in cont["characters"]
        ]
        parts.append(f"Characters: {'; '.join(char_descs)}.")
    if cont.get("setting_notes"):
        parts.append(f"Setting: {cont['setting_notes']}.")


def build_flat_image_prompt(data: dict) -> str:
    """Build a flat text prompt for image generation."""
    parts: list[str] = []
    od = orientation_directive(data.get("orientation"))
    if od:
        parts.append(od)
    gs = data.get("global_style")
    if gs:
        parts.append(
            f"Style: {gs.get('look', '')}. Mood: {gs.get('mood', '')}. "
            f"Colors: {gs.get('color_grading', '')}. Lighting: {gs.get('lighting_style', '')}."
        )
    _append_continuity_parts(parts, data.get("continuity"))
    parts.append(data.get("visual_description", ""))
    return " ".join(parts)


def build_flat_video_prompt(data: dict) -> str:
    """Build a flat text prompt for video generation."""
    parts = _build_video_base_parts(data)
    parts.append(PHYSICAL_REALISM_DIRECTIVE)
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
    for key, label in (
        ("camera_angle", "Camera angle"),
        ("camera_movement", "Camera movement"),
        ("cinematic_style", "Cinematic style"),
    ):
        if md.get(key):
            parts.append(f"{label}: {md[key]}.")
    gs = data.get("global_style")
    pace = md.get("pace") or (gs.get("pace") if gs else None)
    if pace:
        parts.append(f"Pace: {pace}.")
    if gs:
        parts.append(
            f"Style: {gs.get('look', '')}. Mood: {gs.get('mood', '')}. "
            f"Colors: {gs.get('color_grading', '')}. Lighting: {gs.get('lighting_style', '')}."
        )
    _append_continuity_parts(parts, data.get("continuity"))
    parts.append(data.get("visual_description", ""))
    return parts


def _append_transitions(parts: list[str], data: dict) -> None:
    """Append transition directives to prompt parts."""
    if data.get("music_transition"):
        parts.append(f"Music transition: {data['music_transition']}")


def _append_narration(parts: list[str], data: dict) -> None:
    """Append narration directive if enabled."""
    if data.get("narration_enabled"):
        narration = data.get("narration")
        if narration:
            parts.append(f'Voice-over narration: "{narration}"')


def _append_music(parts: list[str], data: dict) -> None:
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
