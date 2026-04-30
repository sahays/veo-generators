"""Unit tests for pricing_config — tier boundaries, per-model dispatch, estimator math."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from pricing_config import (
    DEFAULT_IMAGE_MODEL,
    DEFAULT_TEXT_MODEL,
    DEFAULT_VIDEO_MODEL,
    DIARIZATION,
    FEATURE_SERVICES,
    IMAGE_MODELS,
    TEXT_MODELS,
    TRANSCODER_HD,
    VEO_BY_MODEL,
    VEO_STANDARD,
    cost_for_image,
    cost_for_text,
    cost_for_veo,
    veo_rate_for,
)


class TestGeminiTextTiers:
    def test_pro_below_200k_cutoff(self):
        # 100K input, 5K output. ≤200K tier: $2/1M in, $12/1M out.
        cost = cost_for_text("gemini-3.1-pro-preview", 100_000, 5_000)
        expected = 100_000 * 2e-6 + 5_000 * 12e-6
        assert cost == pytest.approx(expected)

    def test_pro_at_boundary_still_cheap_tier(self):
        # Exactly 200,000 input tokens: still the ≤200K tier.
        cost = cost_for_text("gemini-3.1-pro-preview", 200_000, 0)
        assert cost == pytest.approx(200_000 * 2e-6)

    def test_pro_above_200k_uses_higher_tier(self):
        # 200_001 input: should use $4/1M in, $18/1M out.
        cost = cost_for_text("gemini-3.1-pro-preview", 200_001, 1000)
        expected = 200_001 * 4e-6 + 1000 * 18e-6
        assert cost == pytest.approx(expected)

    def test_flash_lite_is_cheaper_than_pro(self):
        pro = cost_for_text("gemini-3.1-pro-preview", 10_000, 1000)
        lite = cost_for_text("gemini-3.1-flash-lite-preview", 10_000, 1000)
        assert lite < pro
        assert lite == pytest.approx(10_000 * 0.25e-6 + 1000 * 1.5e-6)

    def test_unknown_model_falls_back_to_pro(self):
        unknown = cost_for_text("not-a-real-model", 1000, 500)
        pro = cost_for_text("gemini-3.1-pro-preview", 1000, 500)
        assert unknown == pytest.approx(pro)


class TestGeminiImageTokenBased:
    def test_image_cost_is_token_based(self):
        # 1290 output tokens at $60/1M = ~$0.0774
        cost = cost_for_image("gemini-3.1-flash-image-preview", 0, 1290)
        assert cost == pytest.approx(1290 * 60e-6)
        assert 0.07 < cost < 0.08

    def test_image_cost_includes_input(self):
        cost = cost_for_image("gemini-3.1-flash-image-preview", 400, 1290)
        expected = 400 * 0.5e-6 + 1290 * 60e-6
        assert cost == pytest.approx(expected)

    def test_image_cost_is_NOT_the_legacy_flat_rate(self):
        # Old hardcoded constants were $0.134 and $0.039 — neither matches real.
        cost = cost_for_image("gemini-3.1-flash-image-preview", 400, 1290)
        assert abs(cost - 0.134) > 0.05
        assert abs(cost - 0.039) > 0.03


class TestVeoDispatch:
    def test_standard_rate(self):
        assert cost_for_veo("veo-3.1-generate-001", 8) == pytest.approx(8 * 0.40)

    def test_fast_cheaper_than_standard(self):
        standard = cost_for_veo("veo-3.1-generate-001", 8)
        fast = cost_for_veo("veo-3.1-fast-generate-001", 8)
        assert fast < standard
        assert fast == pytest.approx(8 * 0.15)

    def test_lite_rate(self):
        assert cost_for_veo("veo-3.1-lite-generate-001", 8) == pytest.approx(8 * 0.05)

    def test_unknown_model_falls_back_to_standard(self):
        assert veo_rate_for("not-a-real-model") == VEO_STANDARD


class TestFeatureServices:
    def test_all_features_declared(self):
        expected = {
            "production",
            "adapts",
            "reframe",
            "promo",
            "key_moments",
            "thumbnails",
        }
        assert set(FEATURE_SERVICES.keys()) == expected

    def test_adapts_is_image_only(self):
        assert FEATURE_SERVICES["adapts"] == ["gemini_image"]

    def test_reframe_includes_diarization_and_transcoder(self):
        assert "diarization" in FEATURE_SERVICES["reframe"]
        assert "transcoder" in FEATURE_SERVICES["reframe"]

    def test_promo_does_not_claim_transcoder(self):
        # Promo stitches via local ffmpeg, not Cloud Transcoder.
        assert "transcoder" not in FEATURE_SERVICES["promo"]


class TestCatalogs:
    def test_default_text_model_in_catalog(self):
        assert DEFAULT_TEXT_MODEL in TEXT_MODELS

    def test_default_image_model_in_catalog(self):
        assert DEFAULT_IMAGE_MODEL in IMAGE_MODELS

    def test_default_video_model_in_catalog(self):
        assert DEFAULT_VIDEO_MODEL in VEO_BY_MODEL

    def test_transcoder_hd_rate_matches_google_pricing_april_2026(self):
        assert TRANSCODER_HD.unit_cost_usd == 0.030

    def test_diarization_rate_matches_google_pricing_april_2026(self):
        assert DIARIZATION.unit_cost_usd == 0.016


class TestEstimator:
    """Smoke tests for the estimator endpoint logic — run via the router."""

    def test_estimator_production(self):
        from models import PricingEstimateRequest
        from pricing_estimator import _estimate_production

        req = PricingEstimateRequest(
            feature="production",
            scene_count=3,
            video_length_seconds=24,
        )
        items = _estimate_production(req)
        # Production must include 4 services: text, image, veo, transcoder
        service_ids = [i.id for i in items]
        assert "gemini_text" in service_ids
        assert "gemini_image" in service_ids
        assert "veo" in service_ids
        assert "transcoder_hd" in service_ids

    def test_estimator_adapts_scales_with_variant_count(self):
        from models import PricingEstimateRequest
        from pricing_estimator import _estimate_adapts

        one = _estimate_adapts(
            PricingEstimateRequest(feature="adapts", variant_count=1)
        )
        four = _estimate_adapts(
            PricingEstimateRequest(feature="adapts", variant_count=4)
        )
        assert four[0].subtotal_usd == pytest.approx(4 * one[0].subtotal_usd)

    def test_estimator_reframe_scales_with_duration(self):
        from models import PricingEstimateRequest
        from pricing_estimator import _estimate_reframe

        short = _estimate_reframe(
            PricingEstimateRequest(feature="reframe", source_duration_seconds=60)
        )
        long = _estimate_reframe(
            PricingEstimateRequest(feature="reframe", source_duration_seconds=600)
        )
        # Text cost stays roughly constant; diarization + transcoder grow linearly.
        short_flat = sum(
            i.subtotal_usd for i in short if i.id in ("diarization", "transcoder_hd")
        )
        long_flat = sum(
            i.subtotal_usd for i in long if i.id in ("diarization", "transcoder_hd")
        )
        assert long_flat == pytest.approx(10 * short_flat)

    def test_estimator_unknown_feature_raises(self):
        from fastapi import HTTPException
        from models import PricingEstimateRequest
        from routers.pricing import estimate
        import asyncio

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(estimate(PricingEstimateRequest(feature="bogus")))
        assert exc_info.value.status_code == 400


class TestUsageNormalization:
    """The /usage endpoint converts UsageMetrics → ServiceLineItem[]."""

    def test_empty_usage_produces_no_items(self):
        from models import UsageMetrics
        from pricing_usage import usage_to_line_items as _usage_to_line_items

        items = _usage_to_line_items(UsageMetrics())
        assert items == []

    def test_reframe_usage_produces_text_plus_flat_services(self):
        from models import UsageMetrics
        from pricing_usage import usage_to_line_items as _usage_to_line_items

        usage = UsageMetrics(
            input_tokens=10_000,
            output_tokens=1_000,
            model_name="gemini-3.1-pro-preview",
            cost_usd=0.03 + 0.016 + 0.030,  # text + 1min diar + 1min transcoder
            diarization_minutes=1.0,
            diarization_cost_usd=0.016,
            transcoder_minutes=1.0,
            transcoder_cost_usd=0.030,
        )
        items = _usage_to_line_items(usage)
        ids = [i.id for i in items]
        assert "gemini_text" in ids
        assert "diarization" in ids
        assert "transcoder_hd" in ids

    def test_totals_approximate_match_cost_usd(self):
        """The sum of line-item subtotals should equal the record's cost_usd
        within floating-point tolerance."""
        from models import UsageMetrics
        from pricing_usage import usage_to_line_items as _usage_to_line_items

        usage = UsageMetrics(
            input_tokens=1000,
            output_tokens=500,
            model_name="gemini-3.1-pro-preview",
            cost_usd=0.008,
            veo_videos=1,
            veo_seconds=8,
            veo_unit_cost=0.40,
            veo_cost_usd=3.20,
        )
        # Adjust cost_usd to be the correct sum of components.
        text_only_cost = 1000 * 2e-6 + 500 * 12e-6  # 0.008
        usage.cost_usd = text_only_cost + usage.veo_cost_usd
        items = _usage_to_line_items(usage)
        total = sum(i.subtotal_usd for i in items)
        assert total == pytest.approx(usage.cost_usd, abs=1e-6)
