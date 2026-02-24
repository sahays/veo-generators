from typing import Optional

import deps
from models import Project, Scene


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
