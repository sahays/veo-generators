import asyncio
import logging
from typing import Callable, Optional

from fastapi import HTTPException

import deps
from models import Project, Scene

logger = logging.getLogger(__name__)


# --- Shared Utilities ---


def require_firestore():
    """Raise 503 if Firestore service is not initialized."""
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")


def get_or_404(get_fn: Callable, record_id: str, name: str = "Record"):
    """Fetch a record by ID or raise 404 if not found."""
    record = get_fn(record_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return record


def sign_record_urls(
    record,
    uri_fields: dict[str, str],
    update_fn: Callable[[dict], None],
) -> dict:
    """Generic URL signing for records with a signed_urls cache.

    Args:
        record: Pydantic model with a signed_urls dict field.
        uri_fields: mapping of record field name to output key
            (e.g. {"source_gcs_uri": "source_signed_url"}).
        update_fn: callable to persist updated cache back to Firestore
            (e.g. lambda cache: deps.firestore_svc.update_reframe_record(record.id, {"signed_urls": cache})).

    Returns:
        Record dict with signed URL keys added and signed_urls cache removed.
    """
    data = record.dict()
    if not deps.storage_svc:
        return data

    cache = data.get("signed_urls") or {}
    dirty = False

    for field_name, output_key in uri_fields.items():
        gcs_uri = getattr(record, field_name, None)
        if not gcs_uri:
            continue
        url, changed = deps.storage_svc.resolve_cached_url(gcs_uri, cache)
        data[output_key] = url
        if changed:
            dirty = True

    if dirty and deps.firestore_svc:
        update_fn(cache)

    data.pop("signed_urls", None)
    return data


def list_video_upload_sources() -> list[dict]:
    """Return signed upload video sources. Shared across routers."""
    require_firestore()
    uploads = deps.firestore_svc.get_upload_records(file_type="video")
    results = []
    for u in uploads:
        signed_url = ""
        if deps.storage_svc and u.gcs_uri:
            if u.gcs_uri.startswith("gs://"):
                signed_url = deps.storage_svc.get_signed_url(u.gcs_uri)
            else:
                signed_url = u.gcs_uri
        results.append(
            {
                "id": u.id,
                "filename": u.filename,
                "gcs_uri": u.gcs_uri,
                "video_signed_url": signed_url,
                "file_size_bytes": u.file_size_bytes,
                "createdAt": u.createdAt.isoformat() if u.createdAt else None,
            }
        )
    return results


def list_completed_production_sources(
    extra_fields: Optional[dict[str, str]] = None,
) -> list[dict]:
    """Return signed completed production sources. Shared across routers.

    Args:
        extra_fields: optional mapping of production attribute name to output key
            for router-specific fields (e.g. {"orientation": "orientation", "type": "type"}).
    """
    require_firestore()
    productions = deps.firestore_svc.get_productions()
    completed = [
        p for p in productions if p.status.value == "completed" and p.final_video_url
    ]
    results = []
    for p in completed:
        signed_url = ""
        if deps.storage_svc and p.final_video_url:
            if p.final_video_url.startswith("gs://"):
                signed_url = deps.storage_svc.get_signed_url(p.final_video_url)
            else:
                signed_url = p.final_video_url
        entry = {
            "id": p.id,
            "name": p.name,
            "final_video_url": p.final_video_url,
            "video_signed_url": signed_url,
            "createdAt": p.createdAt.isoformat() if p.createdAt else None,
        }
        if extra_fields:
            for attr, key in extra_fields.items():
                entry[key] = getattr(p, attr, None)
        results.append(entry)
    return results


async def gemini_call_with_retry(
    client,
    model: str,
    contents: list,
    config,
    max_retries: int = 4,
    initial_backoff: int = 2,
):
    """Call client.models.generate_content() with exponential backoff on rate limits.

    Retries on 429 / RESOURCE_EXHAUSTED errors up to max_retries times.
    Returns the Gemini response on success, raises the last error on failure.
    """
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


# --- URL Signing ---


def sign_production_urls(production: Project, thumbnails_only: bool = False) -> dict:
    """Return a dict with media URLs resolved from cache. Re-signs only near expiry.

    When thumbnails_only=True, only sign scene thumbnails (for list views).
    Persists updated signed URL cache back to Firestore when any URL was refreshed.
    """
    if not deps.storage_svc:
        return production.dict()

    data = production.dict()
    cache = data.get("signed_urls") or {}
    dirty = False

    def _resolve(gcs_uri: str) -> str:
        nonlocal dirty
        if not gcs_uri:
            return ""
        # Recover GCS URI from expired signed URLs
        if not gcs_uri.startswith("gs://"):
            recovered = deps.storage_svc.recover_gcs_uri(gcs_uri)
            if recovered:
                gcs_uri = recovered
            else:
                return gcs_uri
        url, changed = deps.storage_svc.resolve_cached_url(gcs_uri, cache)
        if changed:
            dirty = True
        return url

    for scene in data.get("scenes", []):
        if scene.get("thumbnail_url"):
            scene["thumbnail_url"] = _resolve(scene["thumbnail_url"])
        if not thumbnails_only and scene.get("video_url"):
            scene["video_url"] = _resolve(scene["video_url"])
    if not thumbnails_only:
        if data.get("final_video_url"):
            data["final_video_url"] = _resolve(data["final_video_url"])
        if data.get("reference_image_url"):
            data["reference_image_url"] = _resolve(data["reference_image_url"])

    if dirty and deps.firestore_svc:
        deps.firestore_svc.update_production(production.id, {"signed_urls": cache})

    # Don't leak the cache to the client
    data.pop("signed_urls", None)
    return data


# --- Cost Tracking ---


def accumulate_cost(production_id: str, cost_usd: float):
    """Add cost to the production's total_usage without clobbering token data."""
    production = deps.firestore_svc.get_production(production_id)
    if not production:
        return
    current = production.total_usage.cost_usd if production.total_usage else 0.0
    deps.firestore_svc.update_production(
        production_id, {"total_usage.cost_usd": current + cost_usd}
    )


def accumulate_image_cost(production_id: str, cost_per_image: float):
    """Track image generation cost breakdown on total_usage."""
    production = deps.firestore_svc.get_production(production_id)
    if not production:
        return
    usage = production.total_usage
    deps.firestore_svc.update_production(
        production_id,
        {
            "total_usage.cost_usd": (usage.cost_usd if usage else 0.0) + cost_per_image,
            "total_usage.image_generations": (usage.image_generations if usage else 0)
            + 1,
            "total_usage.image_cost_usd": (usage.image_cost_usd if usage else 0.0)
            + cost_per_image,
        },
    )


def accumulate_veo_cost(production_id: str, duration_seconds: int, unit_cost: float):
    """Track Veo video generation cost breakdown on total_usage."""
    production = deps.firestore_svc.get_production(production_id)
    if not production:
        return
    usage = production.total_usage
    veo_cost = duration_seconds * unit_cost
    deps.firestore_svc.update_production(
        production_id,
        {
            "total_usage.cost_usd": (usage.cost_usd if usage else 0.0) + veo_cost,
            "total_usage.veo_videos": (usage.veo_videos if usage else 0) + 1,
            "total_usage.veo_seconds": (usage.veo_seconds if usage else 0)
            + duration_seconds,
            "total_usage.veo_unit_cost": unit_cost,
            "total_usage.veo_cost_usd": (usage.veo_cost_usd if usage else 0.0)
            + veo_cost,
        },
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


def build_flat_image_prompt(data: dict) -> str:
    """Build a flat text prompt for image generation from structured data."""
    parts = []
    od = orientation_directive(data.get("orientation"))
    if od:
        parts.append(od)
    gs = data.get("global_style")
    if gs:
        parts.append(
            f"Style: {gs.get('look', '')}. Mood: {gs.get('mood', '')}. "
            f"Colors: {gs.get('color_grading', '')}. Lighting: {gs.get('lighting_style', '')}."
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
    """Build a flat text prompt for video generation from structured data."""
    parts = []
    duration = data.get("duration", 8)
    parts.append(f"{duration}-second video clip.")
    od = orientation_directive(data.get("orientation"))
    if od:
        parts.append(od)
    md = data.get("metadata", {})
    if md.get("camera_angle"):
        parts.append(f"Camera angle: {md['camera_angle']}.")
    if md.get("camera_movement"):
        parts.append(f"Camera movement: {md['camera_movement']}.")
    if md.get("cinematic_style"):
        parts.append(f"Cinematic style: {md['cinematic_style']}.")
    gs = data.get("global_style")
    pace = md.get("pace") or (gs.get("pace") if gs else None)
    if pace:
        parts.append(f"Pace: {pace}.")
    if gs:
        parts.append(
            f"Style: {gs.get('look', '')}. Mood: {gs.get('mood', '')}. "
            f"Colors: {gs.get('color_grading', '')}. Lighting: {gs.get('lighting_style', '')}."
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

    if data.get("enter_transition"):
        parts.append(data["enter_transition"])
    if data.get("exit_transition"):
        parts.append(data["exit_transition"])
    if data.get("music_transition"):
        parts.append(f"Music transition: {data['music_transition']}")

    # Narration (only if enabled)
    if data.get("narration_enabled"):
        narration = data.get("narration")
        if narration:
            parts.append(f'Voice-over narration: "{narration}"')

    # Music (only if enabled; scene-level falls back to global soundtrack_style)
    if data.get("music_enabled"):
        music = data.get("music_description")
        if not music:
            gs = data.get("global_style")
            if gs and gs.get("soundtrack_style"):
                music = gs["soundtrack_style"]
        if music:
            parts.append(f"Background music: {music}.")

    return " ".join(parts)


def build_prompt_data(scene: Scene, project: Project) -> dict:
    """Build structured prompt data for a scene including all production context."""
    SUPPORTED_DURATIONS = [4, 6, 8]
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
        "global_style": project.global_style.dict() if project.global_style else None,
        "continuity": project.continuity.dict() if project.continuity else None,
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
