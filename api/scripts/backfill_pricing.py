"""Backfill usage facts + pricing confidence on every record in Firestore.

For each record across productions, adapts, reframes, promos, key_moments,
thumbnails: derives missing usage facts (image token counts, transcoder/
diarization minutes, model IDs), tags with pricing_confidence, and recomputes
the denormalized cost_usd cache from current rates in pricing_config.

Defaults to --dry-run. Pass --apply to actually write to Firestore.
"""

import argparse
import logging
import os
import sys
from collections import defaultdict
from typing import Any, Callable, Optional

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


def _log_info(msg: str, where: str = "main") -> None:
    logger.info(
        msg,
        extra={
            "who": "backfill_pricing",
            "where": where,
            "what": msg[:120],
            "why": "Backfill Firestore usage and pricing",
            "how": "script",
        },
    )


def _usage_field(feature: str) -> str:
    return "total_usage" if feature == "production" else "usage"


def _usage_dict(record: Any, feature: str) -> dict:
    usage = getattr(record, _usage_field(feature), None)
    return usage.dict() if usage else {}


def _rank(issues: int) -> str:
    if issues == 0:
        return "high"
    return "medium" if issues == 1 else "low"


def _match_veo_model(unit_cost: float) -> Optional[str]:
    for model_id, rate in VEO_BY_MODEL.items():
        if abs(rate.unit_cost_usd - unit_cost) < 1e-9:
            return model_id
    return None


def _backfill_production(record: Any) -> tuple[dict, str, str]:
    u = _usage_dict(record, "production")
    updates: dict = {}
    notes: list[str] = []
    issues = 0
    if u.get("image_generations", 0) and not u.get("image_model_name"):
        updates["image_model_name"] = DEFAULT_IMAGE_MODEL
        notes.append("image_model_name defaulted")
    if u.get("image_generations", 0) and not u.get("image_output_tokens"):
        est_out = u["image_generations"] * HINTS.image_output_tokens
        updates["image_output_tokens"] = est_out
        updates["image_input_tokens"] = (
            u["image_generations"] * HINTS.image_input_tokens
        )
        notes.append(f"image_output_tokens≈{est_out:,} (1290/img)")
        issues += 1
    if u.get("veo_videos", 0) and not u.get("veo_model_id"):
        matched = _match_veo_model(u.get("veo_unit_cost") or 0)
        updates["veo_model_id"] = matched or DEFAULT_VIDEO_MODEL
        if not matched:
            notes.append("veo_model_id defaulted")
            issues += 1
    if (
        u.get("veo_seconds", 0)
        and getattr(record, "final_video_url", None)
        and not u.get("transcoder_minutes")
    ):
        minutes = u["veo_seconds"] / 60.0
        updates.update({"transcoder_minutes": minutes, "transcoder_tier": "hd"})
        notes.append(f"transcoder≈{minutes:.2f}min (from veo_seconds)")
        issues += 1
    return updates, _rank(issues), "; ".join(notes)


def _backfill_adapts(record: Any) -> tuple[dict, str, str]:
    u = _usage_dict(record, "adapts")
    updates: dict = {}
    notes: list[str] = []
    issues = 0
    count = u.get("image_generations", 0)
    if count and not u.get("image_model_name"):
        updates["image_model_name"] = DEFAULT_IMAGE_MODEL
    if count and not u.get("image_output_tokens"):
        updates["image_output_tokens"] = count * HINTS.image_output_tokens
        updates["image_input_tokens"] = count * HINTS.image_input_tokens
        notes.append(f"image tokens≈{count * HINTS.image_output_tokens:,} (1290/img)")
        issues += 1
    variants = getattr(record, "variants", []) or []
    completed = sum(1 for v in variants if getattr(v, "status", "") == "completed")
    if not count and completed:
        updates.update(
            {
                "image_generations": completed,
                "image_output_tokens": completed * HINTS.image_output_tokens,
                "image_input_tokens": completed * HINTS.image_input_tokens,
                "image_model_name": DEFAULT_IMAGE_MODEL,
            }
        )
        notes.append(f"inferred {completed} generations from variants")
        issues += 1
    return updates, _rank(issues), "; ".join(notes)


def _backfill_reframe(record: Any) -> tuple[dict, str, str]:
    u = _usage_dict(record, "reframe")
    updates: dict = {}
    notes: list[str] = []
    issues = 0
    segments = getattr(record, "speaker_segments", None) or []
    if segments and not u.get("diarization_minutes"):
        max_end = max((getattr(s, "end_sec", 0) or 0) for s in segments)
        if max_end > 0:
            updates["diarization_minutes"] = max_end / 60.0
            notes.append(f"diarization≈{max_end / 60.0:.2f}min (from segments)")
            issues += 1
    if (
        getattr(record, "output_gcs_uri", None)
        and not u.get("transcoder_minutes")
        and updates.get("diarization_minutes")
    ):
        updates["transcoder_minutes"] = updates["diarization_minutes"]
        updates["transcoder_tier"] = "hd"
        notes.append("transcoder≈diarization duration")
    return updates, _rank(issues), "; ".join(notes)


def _backfill_promo(record: Any) -> tuple[dict, str, str]:
    u = _usage_dict(record, "promo")
    updates: dict = {}
    notes: list[str] = []
    issues = 0
    segments = getattr(record, "segments", []) or []
    has_title = bool(getattr(record, "thumbnail_gcs_uri", None))
    with_overlay = sum(1 for s in segments if getattr(s, "overlay_gcs_uri", None))
    image_count = with_overlay + (1 if has_title else 0)
    if image_count > u.get("image_generations", 0):
        updates.update(
            {
                "image_generations": image_count,
                "image_input_tokens": image_count * HINTS.image_input_tokens,
                "image_output_tokens": image_count * HINTS.image_output_tokens,
                "image_model_name": DEFAULT_IMAGE_MODEL,
            }
        )
        notes.append(
            f"inferred {image_count} images ({with_overlay} overlays{' + 1 title' if has_title else ''})"
        )
        issues += 1
    return updates, _rank(issues), "; ".join(notes)


def _backfill_key_moments(record: Any) -> tuple[dict, str, str]:
    u = _usage_dict(record, "key_moments")
    if not u.get("model_name") and (u.get("input_tokens") or u.get("output_tokens")):
        return {"model_name": DEFAULT_TEXT_MODEL}, "high", "model_name defaulted"
    return {}, "high", ""


def _backfill_thumbnails(record: Any) -> tuple[dict, str, str]:
    u = _usage_dict(record, "thumbnails")
    updates: dict = {}
    notes: list[str] = []
    issues = 0
    has_thumb = bool(getattr(record, "thumbnail_gcs_uri", None))
    current = u.get("image_generations", 0)
    if has_thumb and current == 0:
        updates.update(
            {
                "image_generations": 1,
                "image_input_tokens": HINTS.image_input_tokens,
                "image_output_tokens": HINTS.image_output_tokens,
                "image_model_name": DEFAULT_IMAGE_MODEL,
            }
        )
        notes.append("inferred 1 image (thumbnail collage)")
        issues += 1
    elif current and not u.get("image_output_tokens"):
        updates.update(
            {
                "image_output_tokens": current * HINTS.image_output_tokens,
                "image_input_tokens": current * HINTS.image_input_tokens,
                "image_model_name": u.get("image_model_name") or DEFAULT_IMAGE_MODEL,
            }
        )
        notes.append("image tokens estimated")
        issues += 1
    return updates, _rank(issues), "; ".join(notes)


_BACKFILLERS = {
    "production": _backfill_production,
    "adapts": _backfill_adapts,
    "reframe": _backfill_reframe,
    "promo": _backfill_promo,
    "key_moments": _backfill_key_moments,
    "thumbnails": _backfill_thumbnails,
}


def _recompute_veo_cost(merged: dict) -> tuple[float, float]:
    veo_unit = merged.get("veo_unit_cost", 0) or 0
    if not merged.get("veo_videos", 0):
        return 0.0, float(veo_unit)
    veo_model_id = merged.get("veo_model_id")
    rate = VEO_BY_MODEL.get(veo_model_id) or next(
        (r for r in VEO_BY_MODEL.values() if abs(r.unit_cost_usd - veo_unit) < 1e-9),
        VEO_BY_MODEL[DEFAULT_VIDEO_MODEL],
    )
    veo_cost = (merged.get("veo_seconds", 0) or 0) * rate.unit_cost_usd
    return float(veo_cost), float(rate.unit_cost_usd)


def _recompute_costs(merged: dict) -> dict:
    """Given a merged usage dict, return fresh cost_usd and sub-component caches."""
    text_cost = cost_for_text(
        merged.get("model_name") or DEFAULT_TEXT_MODEL,
        merged.get("input_tokens", 0) or 0,
        merged.get("output_tokens", 0) or 0,
    )
    img_cost = (
        cost_for_image(
            merged.get("image_model_name") or DEFAULT_IMAGE_MODEL,
            merged.get("image_input_tokens", 0) or 0,
            merged.get("image_output_tokens", 0) or 0,
        )
        if (merged.get("image_generations", 0) or 0)
        else 0.0
    )
    veo_cost, veo_unit = _recompute_veo_cost(merged)
    tr_cost = (merged.get("transcoder_minutes", 0) or 0) * TRANSCODER_HD.unit_cost_usd
    diar_cost = (merged.get("diarization_minutes", 0) or 0) * DIARIZATION.unit_cost_usd
    total = text_cost + img_cost + veo_cost + tr_cost + diar_cost
    return {
        "cost_usd": round(total, 6),
        "image_cost_usd": round(img_cost, 6),
        "veo_cost_usd": round(veo_cost, 6),
        "veo_unit_cost": round(veo_unit, 6),
        "transcoder_cost_usd": round(tr_cost, 6),
        "diarization_cost_usd": round(diar_cost, 6),
    }


def _iter_records(feature: str) -> list:
    fs = deps.firestore_svc
    getters = {
        "production": fs.get_productions,
        "adapts": fs.get_adapt_records,
        "reframe": fs.get_reframe_records,
        "promo": fs.get_promo_records,
        "key_moments": fs.get_key_moments_analyses,
        "thumbnails": fs.get_thumbnail_records,
    }
    if feature not in getters:
        raise ValueError(f"Unknown feature: {feature}")
    return getters[feature](include_archived=True)


def _update_fn(feature: str) -> Callable:
    fs = deps.firestore_svc
    return {
        "production": fs.update_production,
        "adapts": fs.update_adapt_record,
        "reframe": fs.update_reframe_record,
        "promo": fs.update_promo_record,
        "key_moments": fs.update_key_moments_analysis,
        "thumbnails": fs.update_thumbnail_record,
    }[feature]


def _process_single_record(
    record: Any, feature: str, usage_field: str, backfiller: Callable
) -> tuple[dict, dict, str, str, float, float]:
    existing_usage = _usage_dict(record, feature)
    fact_updates, confidence, note = backfiller(record)
    merged = {**existing_usage, **fact_updates}
    new_costs = _recompute_costs(merged)
    old_total = float(existing_usage.get("cost_usd", 0.0) or 0.0)
    new_total = float(new_costs["cost_usd"])
    updates = {
        f"{usage_field}.{k}": v for k, v in {**fact_updates, **new_costs}.items()
    }
    updates[f"{usage_field}.pricing_confidence"] = confidence
    updates[f"{usage_field}.pricing_notes"] = note
    return updates, fact_updates, confidence, note, old_total, new_total


def _record_backfill_step(
    record: Any,
    feature: str,
    usage_field: str,
    backfiller: Callable,
    updater: Optional[Callable],
    apply: bool,
    state: dict,
) -> None:
    updates, fact_updates, confidence, note, old_total, new_total = (
        _process_single_record(record, feature, usage_field, backfiller)
    )
    state["confidence"][confidence] += 1
    if not fact_updates and abs(old_total - new_total) < 1e-6:
        state["skipped"] += 1
        return
    state["cost_before"] += old_total
    state["cost_after"] += new_total
    if abs(old_total - new_total) > 1e-6:
        state["cost_delta_count"] += 1
    if len(state["samples"]) < 3 and (
        fact_updates or abs(old_total - new_total) > 0.01
    ):
        suffix = f"  [{confidence}] {note}" if note else f"  [{confidence}]"
        state["samples"].append(
            f"  • {record.id}: ${old_total:.4f} → ${new_total:.4f}{suffix}"
        )
    if apply and updater:
        updater(record.id, updates)
    state["touched"] += 1


def _apply_feature(feature: str, apply: bool, limit: Optional[int]) -> dict:
    if not deps.firestore_svc:
        raise RuntimeError("Firestore not initialized")
    records = _iter_records(feature)
    if limit:
        records = records[:limit]
    updater, backfiller, usage_field = (
        _update_fn(feature),
        _BACKFILLERS[feature],
        _usage_field(feature),
    )
    state: dict = {
        "confidence": defaultdict(int),
        "touched": 0,
        "skipped": 0,
        "cost_delta_count": 0,
        "cost_before": 0.0,
        "cost_after": 0.0,
        "samples": [],
    }
    for record in records:
        try:
            _record_backfill_step(
                record, feature, usage_field, backfiller, updater, apply, state
            )
        except Exception as e:
            logger.error(
                f"[{feature}:{record.id}] backfill failed: {e}",
                extra={
                    "who": "backfill_pricing",
                    "where": "_apply_feature",
                    "what": f"Backfill failed for {feature}:{record.id}",
                    "why": str(e),
                    "how": "firestore",
                },
            )
    return {
        "feature": feature,
        "total_records": len(records),
        "touched": state["touched"],
        "skipped": state["skipped"],
        "cost_delta_count": state["cost_delta_count"],
        "cost_before": round(state["cost_before"], 4),
        "cost_after": round(state["cost_after"], 4),
        "confidence": dict(state["confidence"]),
        "samples": state["samples"],
    }


def _log_feature_summary(s: dict) -> None:
    _log_info(
        f"  records={s['total_records']} touched={s['touched']} skipped={s['skipped']} cost_delta_records={s['cost_delta_count']}",
        "_log_feature_summary",
    )
    _log_info(
        f"  sum(cost_usd) before=${s['cost_before']:.4f} after=${s['cost_after']:.4f} delta=${s['cost_after'] - s['cost_before']:+.4f}",
        "_log_feature_summary",
    )
    _log_info(f"  confidence: {dict(s['confidence'])}", "_log_feature_summary")
    if s["samples"]:
        _log_info("  samples:", "_log_feature_summary")
        for line in s["samples"]:
            _log_info(line, "_log_feature_summary")


def _parse_args() -> argparse.Namespace:
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
    return ap.parse_args()


def main() -> None:
    args = _parse_args()
    apply = bool(args.apply)
    mode = "APPLY" if apply else "DRY-RUN"
    _log_info(f"Mode: {mode} | Feature: {args.feature} | Limit: {args.limit}")
    deps.init_services()
    targets = FEATURES if args.feature == "all" else (args.feature,)
    grand_before = grand_after = 0.0
    grand_confidence: dict[str, int] = defaultdict(int)
    for f in targets:
        _log_info(f"--- {f} ---")
        s = _apply_feature(f, apply=apply, limit=args.limit)
        grand_before += s["cost_before"]
        grand_after += s["cost_after"]
        for k, v in s["confidence"].items():
            grand_confidence[k] += v
        _log_feature_summary(s)
    _log_info("=" * 60)
    _log_info(
        f"GRAND TOTAL ({mode}) before=${grand_before:.4f} after=${grand_after:.4f} delta=${grand_after - grand_before:+.4f}"
    )
    _log_info(f"  confidence dist: {dict(grand_confidence)}")
    if not apply:
        _log_info("DRY-RUN — no changes written. Re-run with --apply to persist.")


if __name__ == "__main__":
    main()
