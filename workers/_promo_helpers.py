"""Promo job sub-step helpers: title-card generation + text-overlay compositing.

Lifted out of `PromoProcessor` so the processor stays under the file-size
budget. Each helper takes a `run_async` callback (the processor's
`_run_async`) so it can drive the async Gemini SDK from a sync worker
thread without taking a hard dependency on the class.
"""

import logging
import os
import time
import uuid as _uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Awaitable, Callable, TypeVar

import deps
from cost_tracking import accumulate_image_cost_on

T = TypeVar("T")
RunAsync = Callable[[Awaitable[T]], T]

logger = logging.getLogger(__name__)


# ── Title card flow ─────────────────────────────────────────────────────────


def maybe_prepend_title_card(
    record,
    record_id: str,
    src_path: str,
    segments_raw: list,
    segment_paths: list,
    tmp,
    run_async: RunAsync,
) -> None:
    """If `record.generate_thumbnail`, build a title-card video and prepend it
    to `segment_paths` (in place). Failures are logged and swallowed — the
    rest of the pipeline can still produce a promo without the title card."""
    if not record.generate_thumbnail:
        return
    try:
        _generate_title_card(
            record, record_id, src_path, segments_raw, segment_paths, tmp, run_async
        )
    except Exception as e:
        logger.warning(f"[promo:{record_id}] Title card failed, skipping: {e}")


def _generate_title_card(
    record,
    record_id: str,
    src_path: str,
    segments_raw: list,
    segment_paths: list,
    tmp,
    run_async: RunAsync,
) -> None:
    from ffmpeg_runner import ffprobe_video
    from promo_service import create_title_card_video

    probe = ffprobe_video(src_path)
    orientation = "16:9" if probe["width"] > probe["height"] else "9:16"
    thumb_uri = _get_or_create_thumbnail(
        record, record_id, src_path, segments_raw, orientation, tmp, run_async
    )
    thumb_img = tmp.create(suffix=".png")
    deps.storage_svc.download_to_file(thumb_uri, thumb_img)
    title_card = tmp.create(suffix="_titlecard.mp4")
    create_title_card_video(
        thumb_img, title_card, width=probe["width"], height=probe["height"]
    )
    segment_paths.insert(0, title_card)
    logger.info(f"[promo:{record_id}] Title card prepended")


def _get_or_create_thumbnail(
    record,
    record_id: str,
    src_path: str,
    segments_raw: list,
    orientation: str,
    tmp,
    run_async: RunAsync,
) -> str:
    """Return existing thumbnail URI or generate a new collage."""
    if record.thumbnail_gcs_uri:
        logger.info(f"[promo:{record_id}] Reusing existing thumbnail")
        return record.thumbnail_gcs_uri

    frame_uris = _extract_key_frames(record_id, src_path, segments_raw, tmp)
    result = run_async(
        deps.ai_svc.generate_promo_collage(
            screenshot_uris=frame_uris,
            segments=segments_raw,
            orientation=orientation,
        )
    )
    uri = result.data["image_url"]
    accumulate_image_cost_on(
        "promo",
        record_id,
        result.usage.cost_usd,
        input_tokens=result.usage.image_input_tokens,
        output_tokens=result.usage.image_output_tokens,
    )
    deps.firestore_svc.update_promo_record(record_id, {"thumbnail_gcs_uri": uri})
    return uri


def _extract_key_frames(record_id: str, src_path: str, segments_raw: list, tmp) -> list:
    """Extract frames from the first few key moments and upload to GCS."""
    from promo_service import extract_frame, parse_timestamp

    bucket = os.getenv("GCS_BUCKET")
    key_segments = segments_raw[:4]
    uris: list[str] = []
    for i, seg in enumerate(key_segments):
        mid = (
            parse_timestamp(seg["timestamp_start"])
            + parse_timestamp(seg["timestamp_end"])
        ) / 2
        frame_path = tmp.create(suffix=f"_frame{i}.png")
        extract_frame(src_path, frame_path, mid)
        gcs_path = f"gs://{bucket}/promos/frames/{_uuid.uuid4()}.png"
        uris.append(
            deps.storage_svc.upload_from_file(
                frame_path, gcs_path, content_type="image/png"
            )
        )
        logger.info(f"[promo:{record_id}] Frame {i + 1}/{len(key_segments)}")
    return uris


# ── Text overlay flow ───────────────────────────────────────────────────────


def maybe_apply_text_overlays(
    record,
    record_id: str,
    src_path: str,
    segments_raw: list,
    segment_paths: list,
    tmp,
    run_async: RunAsync,
) -> None:
    """If `record.text_overlay`, generate per-segment overlay images and
    composite them onto each segment (mutates `segment_paths` in place)."""
    if not record.text_overlay:
        return
    from ffmpeg_runner import ffprobe_video

    probe = ffprobe_video(src_path)
    orientation = "16:9" if probe["width"] > probe["height"] else "9:16"
    start_idx = 1 if record.generate_thumbnail else 0
    overlays = _collect_overlay_images(
        record_id, segments_raw, orientation, start_idx, tmp, run_async
    )
    _composite_overlays(record_id, overlays, segment_paths, tmp)


def _collect_overlay_images(
    record_id: str,
    segments_raw: list,
    orientation: str,
    start_idx: int,
    tmp,
    run_async: RunAsync,
) -> list[tuple[int, str]]:
    """Resolve overlay URIs (cached or generated) and download each locally."""
    overlays: list[tuple[int, str]] = []
    for i, seg in enumerate(segments_raw):
        uri = seg.get("overlay_gcs_uri") or _generate_overlay(
            record_id, segments_raw, i, orientation, run_async
        )
        path = tmp.create(suffix=f"_ovr{i}.png")
        deps.storage_svc.download_to_file(uri, path)
        overlays.append((i + start_idx, path))
        logger.info(
            f"[promo:{record_id}] Overlay {i + 1}/{len(segments_raw)}: "
            f"{seg.get('title', '')}"
        )
    return overlays


def _generate_overlay(
    record_id: str,
    segments_raw: list,
    i: int,
    orientation: str,
    run_async: RunAsync,
) -> str:
    """Generate a text overlay image via Gemini, persist URI, return it."""
    if i > 0:
        # Soft-throttle so we don't hammer the image API.
        time.sleep(5)
    result = run_async(
        deps.ai_svc.generate_text_overlay(
            text=segments_raw[i].get("title", ""), orientation=orientation
        )
    )
    uri = result.data["image_url"]
    accumulate_image_cost_on(
        "promo",
        record_id,
        result.usage.cost_usd,
        input_tokens=result.usage.image_input_tokens,
        output_tokens=result.usage.image_output_tokens,
    )
    segments_raw[i]["overlay_gcs_uri"] = uri
    deps.firestore_svc.update_promo_record(record_id, {"segments": segments_raw})
    return uri


def _composite_overlays(
    record_id: str,
    overlays: list[tuple[int, str]],
    segment_paths: list,
    tmp,
) -> None:
    """Apply overlay images to segments in parallel (mutates `segment_paths`)."""
    from promo_service import overlay_image_on_segment

    logger.info(f"[promo:{record_id}] Compositing {len(overlays)} overlays...")

    def apply(seg_idx: int, ovr_path: str):
        out = tmp.create(suffix=f"_overlaid{seg_idx}.mp4")
        overlay_image_on_segment(segment_paths[seg_idx], ovr_path, out)
        return seg_idx, out

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(apply, idx, path) for idx, path in overlays]
        for f in futures:
            idx, out = f.result()
            segment_paths[idx] = out
