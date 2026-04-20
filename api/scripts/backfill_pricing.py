"""Backfill usage facts + pricing confidence on every record in Firestore.

For each record across productions, adapts, reframes, promos, key_moments,
thumbnails: derives missing usage facts (image token counts, transcoder/
diarization minutes, model IDs), tags with pricing_confidence, and recomputes
the denormalized cost_usd cache from current rates in pricing_config.

Defaults to --dry-run. Pass --apply to actually write to Firestore.

Usage:
    cd api && python3 -m scripts.backfill_pricing --dry-run
    cd api && python3 -m scripts.backfill_pricing --apply
    cd api && python3 -m scripts.backfill_pricing --feature adapts --dry-run
"""

import argparse
import logging
import os
import sys
from collections import defaultdict
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import deps  # noqa: E402
from pricing_config import (  # noqa: E402
    DEFAULT_IMAGE_MODEL,
    DEFAULT_TEXT_MODEL,
    DEFAULT_VIDEO_MODEL,
    DIARIZATION,
    HINTS,
    TRANSCODER_HD,
    VEO_BY_MODEL,
    cost_for_image,
    cost_for_text,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("backfill_pricing")


FEATURES = ("production", "adapts", "reframe", "promo", "key_moments", "thumbnails")


def _usage_field(feature: str) -> str:
    return "total_usage" if feature == "production" else "usage"


def _usage_dict(record, feature: str) -> dict:
    usage = getattr(record, _usage_field(feature), None)
    return usage.dict() if usage else {}


# ---------------------------------------------------------------------------
# Per-feature backfill logic. Each function returns (updates_dict, confidence,
# notes) — the updates dict is keyed by top-level Firestore field paths.
# ---------------------------------------------------------------------------


def _backfill_production(record) -> tuple[dict, str, str]:
    u = _usage_dict(record, "production")
    updates, notes, confidence_issues = {}, [], 0

    # Image model
    if u.get("image_generations", 0) and not u.get("image_model_name"):
        updates["image_model_name"] = DEFAULT_IMAGE_MODEL
        notes.append("image_model_name defaulted")

    # Image output tokens (estimate from image_generations × 1290)
    if u.get("image_generations", 0) and not u.get("image_output_tokens"):
        est_out = u["image_generations"] * HINTS.image_output_tokens
        est_in = u["image_generations"] * HINTS.image_input_tokens
        updates["image_output_tokens"] = est_out
        updates["image_input_tokens"] = est_in
        notes.append(f"image_output_tokens≈{est_out:,} (1290/img)")
        confidence_issues += 1

    # Veo model ID from veo_unit_cost
    if u.get("veo_videos", 0) and not u.get("veo_model_id"):
        unit_cost = u.get("veo_unit_cost") or 0
        matched = None
        for model_id, rate in VEO_BY_MODEL.items():
            if abs(rate.unit_cost_usd - unit_cost) < 1e-9:
                matched = model_id
                break
        updates["veo_model_id"] = matched or DEFAULT_VIDEO_MODEL
        if not matched:
            notes.append("veo_model_id defaulted")
            confidence_issues += 1

    # Transcoder: estimate from veo_seconds if production completed stitch
    if (
        u.get("veo_seconds", 0)
        and getattr(record, "final_video_url", None)
        and not u.get("transcoder_minutes")
    ):
        minutes = u["veo_seconds"] / 60.0
        updates["transcoder_minutes"] = minutes
        updates["transcoder_tier"] = "hd"
        notes.append(f"transcoder≈{minutes:.2f}min (from veo_seconds)")
        confidence_issues += 1

    confidence = _rank(confidence_issues)
    return updates, confidence, "; ".join(notes)


def _backfill_adapts(record) -> tuple[dict, str, str]:
    u = _usage_dict(record, "adapts")
    updates, notes, confidence_issues = {}, [], 0
    count = u.get("image_generations", 0)

    if count and not u.get("image_model_name"):
        updates["image_model_name"] = DEFAULT_IMAGE_MODEL

    if count and not u.get("image_output_tokens"):
        updates["image_output_tokens"] = count * HINTS.image_output_tokens
        updates["image_input_tokens"] = count * HINTS.image_input_tokens
        notes.append(f"image tokens≈{count * HINTS.image_output_tokens:,} (1290/img)")
        confidence_issues += 1

    # If image_generations is 0 but variants exist, infer from completed variants.
    variants = getattr(record, "variants", []) or []
    completed = sum(1 for v in variants if getattr(v, "status", "") == "completed")
    if not count and completed:
        updates["image_generations"] = completed
        updates["image_output_tokens"] = completed * HINTS.image_output_tokens
        updates["image_input_tokens"] = completed * HINTS.image_input_tokens
        updates["image_model_name"] = DEFAULT_IMAGE_MODEL
        notes.append(f"inferred {completed} generations from variants")
        confidence_issues += 1

    confidence = _rank(confidence_issues)
    return updates, confidence, "; ".join(notes)


def _backfill_reframe(record) -> tuple[dict, str, str]:
    u = _usage_dict(record, "reframe")
    updates, notes, confidence_issues = {}, [], 0

    # Estimate diarization minutes from stored speaker_segments (authoritative).
    segments = getattr(record, "speaker_segments", None) or []
    if segments and not u.get("diarization_minutes"):
        max_end = max((getattr(s, "end_sec", 0) or 0) for s in segments)
        if max_end > 0:
            updates["diarization_minutes"] = max_end / 60.0
            notes.append(f"diarization≈{max_end / 60.0:.2f}min (from segments)")
            confidence_issues += 1

    # Transcoder minutes: if output exists and diarization was run, assume
    # same duration as audio. Otherwise skip (no way to probe without download).
    if (
        getattr(record, "output_gcs_uri", None)
        and not u.get("transcoder_minutes")
        and updates.get("diarization_minutes")
    ):
        updates["transcoder_minutes"] = updates["diarization_minutes"]
        updates["transcoder_tier"] = "hd"
        notes.append("transcoder≈diarization duration")

    confidence = _rank(confidence_issues)
    return updates, confidence, "; ".join(notes)


def _backfill_promo(record) -> tuple[dict, str, str]:
    u = _usage_dict(record, "promo")
    updates, notes, confidence_issues = {}, [], 0

    segments = getattr(record, "segments", []) or []
    has_title = bool(getattr(record, "thumbnail_gcs_uri", None))
    # Count segments that have overlay_gcs_uri as confirmed image gens
    with_overlay = sum(1 for s in segments if getattr(s, "overlay_gcs_uri", None))
    image_count = with_overlay + (1 if has_title else 0)

    current = u.get("image_generations", 0)
    if image_count > current:
        updates["image_generations"] = image_count
        updates["image_input_tokens"] = image_count * HINTS.image_input_tokens
        updates["image_output_tokens"] = image_count * HINTS.image_output_tokens
        updates["image_model_name"] = DEFAULT_IMAGE_MODEL
        notes.append(
            f"inferred {image_count} images ({with_overlay} overlays"
            f"{' + 1 title' if has_title else ''})"
        )
        confidence_issues += 1

    confidence = _rank(confidence_issues)
    return updates, confidence, "; ".join(notes)


def _backfill_key_moments(record) -> tuple[dict, str, str]:
    # Text-only feature. If input/output tokens are present, we already have
    # everything we need — cost is recomputed at read.
    u = _usage_dict(record, "key_moments")
    if not u.get("model_name") and (u.get("input_tokens") or u.get("output_tokens")):
        return {"model_name": DEFAULT_TEXT_MODEL}, "high", "model_name defaulted"
    return {}, "high", ""


def _backfill_thumbnails(record) -> tuple[dict, str, str]:
    u = _usage_dict(record, "thumbnails")
    updates, notes, confidence_issues = {}, [], 0

    # Thumbnails has text analysis + optional final thumbnail image generation.
    has_thumb = bool(getattr(record, "thumbnail_gcs_uri", None))
    current = u.get("image_generations", 0)
    if has_thumb and current == 0:
        updates["image_generations"] = 1
        updates["image_input_tokens"] = HINTS.image_input_tokens
        updates["image_output_tokens"] = HINTS.image_output_tokens
        updates["image_model_name"] = DEFAULT_IMAGE_MODEL
        notes.append("inferred 1 image (thumbnail collage)")
        confidence_issues += 1
    elif current and not u.get("image_output_tokens"):
        updates["image_output_tokens"] = current * HINTS.image_output_tokens
        updates["image_input_tokens"] = current * HINTS.image_input_tokens
        updates["image_model_name"] = u.get("image_model_name") or DEFAULT_IMAGE_MODEL
        notes.append("image tokens estimated")
        confidence_issues += 1

    confidence = _rank(confidence_issues)
    return updates, confidence, "; ".join(notes)


_BACKFILLERS = {
    "production": _backfill_production,
    "adapts": _backfill_adapts,
    "reframe": _backfill_reframe,
    "promo": _backfill_promo,
    "key_moments": _backfill_key_moments,
    "thumbnails": _backfill_thumbnails,
}


def _rank(issues: int) -> str:
    if issues == 0:
        return "high"
    if issues == 1:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Cost recomputation from current rates (writes to denormalized cache)
# ---------------------------------------------------------------------------


def _recompute_costs(merged: dict) -> dict:
    """Given a merged usage dict (existing + backfilled), return fresh cost_usd
    and sub-component caches computed from current rates."""
    text_cost = cost_for_text(
        merged.get("model_name") or DEFAULT_TEXT_MODEL,
        merged.get("input_tokens", 0) or 0,
        merged.get("output_tokens", 0) or 0,
    )
    img_count = merged.get("image_generations", 0) or 0
    img_cost = 0.0
    if img_count:
        img_cost = cost_for_image(
            merged.get("image_model_name") or DEFAULT_IMAGE_MODEL,
            merged.get("image_input_tokens", 0) or 0,
            merged.get("image_output_tokens", 0) or 0,
        )

    veo_cost = 0.0
    veo_unit = merged.get("veo_unit_cost", 0) or 0
    veo_model_id = merged.get("veo_model_id")
    if merged.get("veo_videos", 0):
        rate = VEO_BY_MODEL.get(veo_model_id) or next(
            (
                r
                for r in VEO_BY_MODEL.values()
                if abs(r.unit_cost_usd - veo_unit) < 1e-9
            ),
            VEO_BY_MODEL[DEFAULT_VIDEO_MODEL],
        )
        veo_cost = (merged.get("veo_seconds", 0) or 0) * rate.unit_cost_usd
        veo_unit = rate.unit_cost_usd

    transcoder_minutes = merged.get("transcoder_minutes", 0) or 0
    tr_cost = transcoder_minutes * TRANSCODER_HD.unit_cost_usd
    diar_minutes = merged.get("diarization_minutes", 0) or 0
    diar_cost = diar_minutes * DIARIZATION.unit_cost_usd

    total = text_cost + img_cost + veo_cost + tr_cost + diar_cost
    return {
        "cost_usd": round(total, 6),
        "image_cost_usd": round(img_cost, 6),
        "veo_cost_usd": round(veo_cost, 6),
        "veo_unit_cost": round(veo_unit, 6),
        "transcoder_cost_usd": round(tr_cost, 6),
        "diarization_cost_usd": round(diar_cost, 6),
    }


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def _iter_records(feature: str) -> list:
    fs = deps.firestore_svc
    if feature == "production":
        return fs.get_productions(include_archived=True)
    if feature == "adapts":
        return fs.get_adapt_records(include_archived=True)
    if feature == "reframe":
        return fs.get_reframe_records(include_archived=True)
    if feature == "promo":
        return fs.get_promo_records(include_archived=True)
    if feature == "key_moments":
        return fs.get_key_moments_analyses(include_archived=True)
    if feature == "thumbnails":
        return fs.get_thumbnail_records(include_archived=True)
    raise ValueError(f"Unknown feature: {feature}")


def _update_fn(feature: str):
    fs = deps.firestore_svc
    return {
        "production": fs.update_production,
        "adapts": fs.update_adapt_record,
        "reframe": fs.update_reframe_record,
        "promo": fs.update_promo_record,
        "key_moments": fs.update_key_moments_analysis,
        "thumbnails": fs.update_thumbnail_record,
    }[feature]


def _apply_feature(feature: str, apply: bool, limit: Optional[int]) -> dict:
    fs = deps.firestore_svc
    if not fs:
        raise RuntimeError("Firestore not initialized")

    records = _iter_records(feature)
    if limit:
        records = records[:limit]

    updater = _update_fn(feature)
    backfiller = _BACKFILLERS[feature]
    usage_field = _usage_field(feature)

    confidence_counts: dict[str, int] = defaultdict(int)
    touched = skipped = cost_delta_count = 0
    total_cost_before = total_cost_after = 0.0
    sample_examples = []

    for record in records:
        try:
            existing_usage = _usage_dict(record, feature)
            fact_updates, confidence, note = backfiller(record)

            merged = {**existing_usage, **fact_updates}
            new_costs = _recompute_costs(merged)

            old_total = existing_usage.get("cost_usd", 0.0) or 0.0
            new_total = new_costs["cost_usd"]

            # Build the dotted update path
            updates = {}
            for key, value in fact_updates.items():
                updates[f"{usage_field}.{key}"] = value
            for key, value in new_costs.items():
                updates[f"{usage_field}.{key}"] = value
            updates[f"{usage_field}.pricing_confidence"] = confidence
            updates[f"{usage_field}.pricing_notes"] = note
            confidence_counts[confidence] += 1

            if not fact_updates and abs(old_total - new_total) < 1e-6:
                skipped += 1
                continue

            total_cost_before += old_total
            total_cost_after += new_total
            if abs(old_total - new_total) > 1e-6:
                cost_delta_count += 1

            if len(sample_examples) < 3 and (
                fact_updates or abs(old_total - new_total) > 0.01
            ):
                sample_examples.append(
                    f"  • {record.id}: ${old_total:.4f} → ${new_total:.4f}"
                    + (f"  [{confidence}] {note}" if note else f"  [{confidence}]")
                )

            if apply and updater:
                updater(record.id, updates)
            touched += 1

        except Exception as e:
            logger.error(f"[{feature}:{record.id}] backfill failed: {e}")

    return {
        "feature": feature,
        "total_records": len(records),
        "touched": touched,
        "skipped": skipped,
        "cost_delta_count": cost_delta_count,
        "cost_before": round(total_cost_before, 4),
        "cost_after": round(total_cost_after, 4),
        "confidence": dict(confidence_counts),
        "samples": sample_examples,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Show what would change without writing (default)",
    )
    ap.add_argument("--apply", action="store_true", help="Actually write to Firestore")
    ap.add_argument("--feature", choices=list(FEATURES) + ["all"], default="all")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    apply = args.apply  # --apply overrides --dry-run
    mode = "APPLY" if apply else "DRY-RUN"
    logger.info(f"Mode: {mode} | Feature: {args.feature} | Limit: {args.limit}")

    deps.init_services()

    targets = FEATURES if args.feature == "all" else (args.feature,)
    summaries = []
    grand_before = grand_after = 0.0
    grand_confidence = defaultdict(int)
    for f in targets:
        logger.info(f"--- {f} ---")
        s = _apply_feature(f, apply=apply, limit=args.limit)
        summaries.append(s)
        grand_before += s["cost_before"]
        grand_after += s["cost_after"]
        for k, v in s["confidence"].items():
            grand_confidence[k] += v
        logger.info(
            f"  records={s['total_records']} touched={s['touched']} "
            f"skipped={s['skipped']} cost_delta_records={s['cost_delta_count']}"
        )
        logger.info(
            f"  sum(cost_usd) before=${s['cost_before']:.4f} "
            f"after=${s['cost_after']:.4f} "
            f"delta=${s['cost_after'] - s['cost_before']:+.4f}"
        )
        logger.info(f"  confidence: {dict(s['confidence'])}")
        if s["samples"]:
            logger.info("  samples:")
            for line in s["samples"]:
                logger.info(line)

    logger.info("=" * 60)
    logger.info(f"GRAND TOTAL ({mode})")
    logger.info(f"  cost_usd before: ${grand_before:.4f}")
    logger.info(f"  cost_usd after:  ${grand_after:.4f}")
    logger.info(f"  delta:           ${grand_after - grand_before:+.4f}")
    logger.info(f"  confidence dist: {dict(grand_confidence)}")
    if not apply:
        logger.info("DRY-RUN — no changes written. Re-run with --apply to persist.")


if __name__ == "__main__":
    main()
