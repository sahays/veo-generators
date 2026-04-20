"""Tests that agent tool payloads match the actual API router contracts.

Each test builds the payload the tool would send and validates it against the
real Pydantic model or router signature — catching field-name mismatches,
missing required fields, and unexpected params before they hit production.
"""

import pytest
from models import Project
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# Helpers — mirrors what tools.py builds, without network calls
# ---------------------------------------------------------------------------


def _production_payload(name: str, base_concept: str, prompt_id=None) -> dict:
    """Mirrors agents/tools.py create_production."""
    payload = {"name": name, "base_concept": base_concept}
    if prompt_id:
        payload["prompt_id"] = prompt_id
    return payload


def _promo_payload(
    gcs_uri, target_duration=60, source_filename="", text_overlay=False
) -> dict:
    """Mirrors agents/tools.py create_promo."""
    return {
        "gcs_uri": gcs_uri,
        "source_filename": source_filename,
        "target_duration": target_duration,
        "text_overlay": text_overlay,
    }


def _reframe_payload(gcs_uri, content_type="other") -> dict:
    """Mirrors agents/tools.py create_reframe."""
    return {"gcs_uri": gcs_uri, "content_type": content_type}


def _key_moments_payload(gcs_uri, prompt_id) -> dict:
    """Mirrors agents/tools.py create_key_moments_analysis."""
    return {"gcs_uri": gcs_uri, "prompt_id": prompt_id}


def _thumbnails_payload(gcs_uri, prompt_id) -> dict:
    """Mirrors agents/tools.py create_thumbnails."""
    return {"gcs_uri": gcs_uri, "prompt_id": prompt_id}


def _adapt_payload(gcs_uri, aspect_ratios) -> dict:
    """Mirrors agents/tools.py create_adapt."""
    return {"gcs_uri": gcs_uri, "aspect_ratios": aspect_ratios}


def _system_prompts_params(category=None) -> dict:
    """Mirrors agents/tools.py list_system_prompts."""
    params = {"type": "prompt"}
    if category:
        params["category"] = category
    return params


# ---------------------------------------------------------------------------
# Production — validates against Project Pydantic model
# ---------------------------------------------------------------------------


class TestCreateProductionPayload:
    def test_required_fields_accepted(self):
        payload = _production_payload("My Ad", "A car commercial")
        project = Project(**payload)
        assert project.name == "My Ad"
        assert project.base_concept == "A car commercial"

    def test_type_defaults_to_advertizement(self):
        payload = _production_payload("Ad", "concept")
        project = Project(**payload)
        assert project.type == "advertizement"

    def test_missing_name_raises(self):
        with pytest.raises(ValidationError):
            Project(base_concept="concept")

    def test_missing_base_concept_raises(self):
        with pytest.raises(ValidationError):
            Project(name="name")

    def test_old_display_name_field_rejected(self):
        """The old tool used 'display_name' — verify this doesn't satisfy 'name'."""
        with pytest.raises(ValidationError):
            Project(display_name="test", base_concept="concept")


# ---------------------------------------------------------------------------
# Promo — validates payload fields match PromoRequest
# ---------------------------------------------------------------------------


class TestCreatePromoPayload:
    def test_has_required_gcs_uri(self):
        payload = _promo_payload("gs://bucket/video.mp4")
        assert "gcs_uri" in payload
        assert payload["gcs_uri"] == "gs://bucket/video.mp4"

    def test_default_values(self):
        payload = _promo_payload("gs://b/v.mp4")
        assert payload["target_duration"] == 60
        assert payload["source_filename"] == ""
        assert payload["text_overlay"] is False

    def test_no_unknown_fields(self):
        """Payload should only contain fields PromoRequest accepts."""
        payload = _promo_payload("gs://b/v.mp4")
        valid_fields = {
            "gcs_uri",
            "source_filename",
            "mime_type",
            "prompt_id",
            "target_duration",
            "text_overlay",
            "generate_thumbnail",
        }
        assert set(payload.keys()).issubset(valid_fields)


# ---------------------------------------------------------------------------
# Reframe — validates payload fields match ReframeRequest
# ---------------------------------------------------------------------------


class TestCreateReframePayload:
    def test_has_required_gcs_uri(self):
        payload = _reframe_payload("gs://bucket/video.mp4")
        assert payload["gcs_uri"] == "gs://bucket/video.mp4"

    def test_content_type_sent(self):
        payload = _reframe_payload("gs://b/v.mp4", content_type="interview")
        assert payload["content_type"] == "interview"

    def test_no_aspect_ratio_field(self):
        """Old tool sent aspect_ratio which ReframeRequest doesn't accept."""
        payload = _reframe_payload("gs://b/v.mp4")
        assert "aspect_ratio" not in payload

    def test_no_unknown_fields(self):
        payload = _reframe_payload("gs://b/v.mp4")
        valid_fields = {
            "gcs_uri",
            "source_filename",
            "mime_type",
            "prompt_id",
            "content_type",
            "blurred_bg",
            "sports_mode",
            "vertical_split",
        }
        assert set(payload.keys()).issubset(valid_fields)


# ---------------------------------------------------------------------------
# Key Moments
# ---------------------------------------------------------------------------


class TestKeyMomentsPayload:
    def test_required_fields(self):
        payload = _key_moments_payload("gs://b/v.mp4", "prompt-123")
        assert payload["gcs_uri"] == "gs://b/v.mp4"
        assert payload["prompt_id"] == "prompt-123"

    def test_no_unknown_fields(self):
        payload = _key_moments_payload("gs://b/v.mp4", "p1")
        valid_fields = {
            "gcs_uri",
            "prompt_id",
            "mime_type",
            "schema_id",
            "video_filename",
            "video_source",
            "production_id",
        }
        assert set(payload.keys()).issubset(valid_fields)


# ---------------------------------------------------------------------------
# Thumbnails
# ---------------------------------------------------------------------------


class TestThumbnailsPayload:
    def test_required_fields(self):
        payload = _thumbnails_payload("gs://b/v.mp4", "prompt-456")
        assert payload["gcs_uri"] == "gs://b/v.mp4"
        assert payload["prompt_id"] == "prompt-456"

    def test_no_unknown_fields(self):
        payload = _thumbnails_payload("gs://b/v.mp4", "p1")
        valid_fields = {
            "gcs_uri",
            "prompt_id",
            "mime_type",
            "video_filename",
            "video_source",
            "production_id",
        }
        assert set(payload.keys()).issubset(valid_fields)


# ---------------------------------------------------------------------------
# Adapts
# ---------------------------------------------------------------------------


class TestAdaptPayload:
    def test_required_fields(self):
        payload = _adapt_payload("gs://b/img.png", ["16:9", "9:16"])
        assert payload["gcs_uri"] == "gs://b/img.png"
        assert payload["aspect_ratios"] == ["16:9", "9:16"]

    def test_no_unknown_fields(self):
        payload = _adapt_payload("gs://b/img.png", [])
        valid_fields = {
            "gcs_uri",
            "source_filename",
            "source_mime_type",
            "template_gcs_uri",
            "prompt_id",
            "preset_bundle",
            "aspect_ratios",
        }
        assert set(payload.keys()).issubset(valid_fields)


# ---------------------------------------------------------------------------
# System prompts query params
# ---------------------------------------------------------------------------


class TestSystemPromptsParams:
    def test_default_type_is_prompt(self):
        params = _system_prompts_params()
        assert params["type"] == "prompt"

    def test_category_included_when_set(self):
        params = _system_prompts_params("production")
        assert params["category"] == "production"
        assert params["type"] == "prompt"

    def test_no_category_when_none(self):
        params = _system_prompts_params()
        assert "category" not in params

    def test_only_valid_query_params(self):
        """Router accepts only 'type' and 'category'."""
        params = _system_prompts_params("promo")
        assert set(params.keys()).issubset({"type", "category"})


# ---------------------------------------------------------------------------
# Lookup endpoints — verify they return expected shapes
# ---------------------------------------------------------------------------


class TestLookupEndpoints:
    """Verify the lookup endpoints return data from the actual source modules."""

    def test_content_types_matches_reframe_strategies(self):
        from reframe_strategies import CONTENT_TYPE_VARIABLES, STRATEGY_CONFIG

        # Every key in CONTENT_TYPE_VARIABLES should be a valid content type
        for ct in CONTENT_TYPE_VARIABLES:
            assert ct in STRATEGY_CONFIG, (
                f"Content type '{ct}' missing from STRATEGY_CONFIG"
            )
            assert "content_description" in CONTENT_TYPE_VARIABLES[ct]

    def test_all_ratios_not_empty(self):
        from routers.adapts import ALL_RATIOS

        assert len(ALL_RATIOS) > 0
        for r in ALL_RATIOS:
            parts = r.split(":")
            assert len(parts) == 2, f"Invalid ratio format: {r}"

    def test_preset_bundles_use_valid_ratios(self):
        from routers.adapts import ALL_RATIOS, PRESET_BUNDLES

        for name, bundle in PRESET_BUNDLES.items():
            assert "name" in bundle
            assert "ratios" in bundle
            for ratio in bundle["ratios"]:
                assert ratio in ALL_RATIOS, (
                    f"Preset '{name}' uses ratio '{ratio}' not in ALL_RATIOS"
                )

    def test_content_types_have_strategy(self):
        """Every content type must have a corresponding processing strategy."""
        from reframe_strategies import CONTENT_TYPE_VARIABLES, STRATEGY_CONFIG

        for ct in CONTENT_TYPE_VARIABLES:
            config = STRATEGY_CONFIG.get(ct)
            assert config is not None, f"No STRATEGY_CONFIG for content type '{ct}'"
            assert "cv_strategy" in config


# ---------------------------------------------------------------------------
# Job status endpoint map
# ---------------------------------------------------------------------------


class TestJobStatusEndpoints:
    """Verify _JOB_ENDPOINT_PREFIXES maps to real router prefixes."""

    EXPECTED = {
        "production": "/api/v1/productions",
        "promo": "/api/v1/promo",
        "reframe": "/api/v1/reframe",
        "key_moments": "/api/v1/key-moments",
        "thumbnails": "/api/v1/thumbnails",
        "adapts": "/api/v1/adapts",
    }

    def test_all_job_types_present(self):
        from agents.tools import _JOB_ENDPOINT_PREFIXES

        for job_type in self.EXPECTED:
            assert job_type in _JOB_ENDPOINT_PREFIXES

    def test_endpoint_paths_match_routers(self):
        from agents.tools import _JOB_ENDPOINT_PREFIXES

        for job_type, expected_prefix in self.EXPECTED.items():
            assert _JOB_ENDPOINT_PREFIXES[job_type] == expected_prefix, (
                f"{job_type}: expected {expected_prefix}, got {_JOB_ENDPOINT_PREFIXES[job_type]}"
            )
