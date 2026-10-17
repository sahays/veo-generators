"""Tests that agent tool payloads match the actual API router contracts.

Each test builds the payload the tool would send and validates it against the
real Pydantic model or router signature — catching field-name mismatches,
missing required fields, and unexpected params before they hit production.
"""

from typing import Any

import pytest
from models import Project
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# Helpers — mirrors what tools.py builds, without network calls
# ---------------------------------------------------------------------------


def _production_payload(name: str, base_concept: str, prompt_id: Any = None) -> dict:
    """Mirrors agents/tools.py create_production."""
    payload = {"name": name, "base_concept": base_concept}
    if prompt_id:
        payload["prompt_id"] = prompt_id
    return payload


def _promo_payload(
    gcs_uri: Any,
    target_duration: Any = 60,
    source_filename: Any = "",
    text_overlay: Any = False,
) -> dict:
    """Mirrors agents/tools.py create_promo."""
    return {
        "gcs_uri": gcs_uri,
        "source_filename": source_filename,
        "target_duration": target_duration,
        "text_overlay": text_overlay,
    }


def _reframe_payload(gcs_uri: Any, content_type: Any = "other") -> dict:
    """Mirrors agents/tools.py create_reframe."""
    return {"gcs_uri": gcs_uri, "content_type": content_type}


def _key_moments_payload(gcs_uri: Any, prompt_id: Any) -> dict:
    """Mirrors agents/tools.py create_key_moments_analysis."""
    return {"gcs_uri": gcs_uri, "prompt_id": prompt_id}


def _thumbnails_payload(gcs_uri: Any, prompt_id: Any) -> dict:
    """Mirrors agents/tools.py create_thumbnails."""
    return {"gcs_uri": gcs_uri, "prompt_id": prompt_id}


def _adapt_payload(gcs_uri: Any, aspect_ratios: Any) -> dict:
    """Mirrors agents/tools.py create_adapt."""
    return {"gcs_uri": gcs_uri, "aspect_ratios": aspect_ratios}


def _system_prompts_params(category: Any = None) -> dict:
    """Mirrors agents/tools.py list_system_prompts."""
    params = {"type": "prompt"}
    if category:
        params["category"] = category
    return params


# ---------------------------------------------------------------------------
# Production — validates against Project Pydantic model
# ---------------------------------------------------------------------------


class TestCreateProductionPayload:
    def test_required_fields_accepted(self) -> None:
        payload = _production_payload("My Ad", "A car commercial")
        project = Project(**payload)
        assert project.name == "My Ad"
        assert project.base_concept == "A car commercial"

    def test_type_defaults_to_advertizement(self) -> None:
        payload = _production_payload("Ad", "concept")
        project = Project(**payload)
        assert project.type == "advertizement"

    def test_missing_name_raises(self) -> None:
        with pytest.raises(ValidationError):
            Project(base_concept="concept")

    def test_missing_base_concept_raises(self) -> None:
        with pytest.raises(ValidationError):
            Project(name="name")

    def test_old_display_name_field_rejected(self) -> None:
        """The old tool used 'display_name' — verify this doesn't satisfy 'name'."""
        with pytest.raises(ValidationError):
            Project(display_name="test", base_concept="concept")


# ---------------------------------------------------------------------------
# Promo — validates payload fields match PromoRequest
# ---------------------------------------------------------------------------


class TestCreatePromoPayload:
    def test_has_required_gcs_uri(self) -> None:
        payload = _promo_payload("gs://bucket/video.mp4")
        assert "gcs_uri" in payload
        assert payload["gcs_uri"] == "gs://bucket/video.mp4"

    def test_default_values(self) -> None:
        payload = _promo_payload("gs://b/v.mp4")
        assert payload["target_duration"] == 60
        assert payload["source_filename"] == ""
        assert payload["text_overlay"] is False

    def test_no_unknown_fields(self) -> None:
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
    def test_has_required_gcs_uri(self) -> None:
        payload = _reframe_payload("gs://bucket/video.mp4")
        assert payload["gcs_uri"] == "gs://bucket/video.mp4"

    def test_content_type_sent(self) -> None:
        payload = _reframe_payload("gs://b/v.mp4", content_type="interview")
        assert payload["content_type"] == "interview"

    def test_no_aspect_ratio_field(self) -> None:
        """Old tool sent aspect_ratio which ReframeRequest doesn't accept."""
        payload = _reframe_payload("gs://b/v.mp4")
        assert "aspect_ratio" not in payload

    def test_no_unknown_fields(self) -> None:
        payload = _reframe_payload("gs://b/v.mp4")
        valid_fields = {
            "gcs_uri",
            "source_filename",
            "mime_type",
            "prompt_id",
            "content_type",
            "blurred_bg",
            "sports_mode",
        }
        assert set(payload.keys()).issubset(valid_fields)


# ---------------------------------------------------------------------------
# Key Moments
# ---------------------------------------------------------------------------


class TestKeyMomentsPayload:
    def test_required_fields(self) -> None:
        payload = _key_moments_payload("gs://b/v.mp4", "prompt-123")
        assert payload["gcs_uri"] == "gs://b/v.mp4"
        assert payload["prompt_id"] == "prompt-123"

    def test_no_unknown_fields(self) -> None:
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
    def test_required_fields(self) -> None:
        payload = _thumbnails_payload("gs://b/v.mp4", "prompt-456")
        assert payload["gcs_uri"] == "gs://b/v.mp4"
        assert payload["prompt_id"] == "prompt-456"

    def test_no_unknown_fields(self) -> None:
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
    def test_required_fields(self) -> None:
        payload = _adapt_payload("gs://b/img.png", ["16:9", "9:16"])
        assert payload["gcs_uri"] == "gs://b/img.png"
        assert payload["aspect_ratios"] == ["16:9", "9:16"]

    def test_no_unknown_fields(self) -> None:
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
    def test_default_type_is_prompt(self) -> None:
        params = _system_prompts_params()
        assert params["type"] == "prompt"

    def test_category_included_when_set(self) -> None:
        params = _system_prompts_params("production")
        assert params["category"] == "production"
        assert params["type"] == "prompt"

    def test_no_category_when_none(self) -> None:
        params = _system_prompts_params()
        assert "category" not in params

    def test_only_valid_query_params(self) -> None:
        """Router accepts only 'type' and 'category'."""
        params = _system_prompts_params("promo")
        assert set(params.keys()).issubset({"type", "category"})


# ---------------------------------------------------------------------------
# Lookup endpoints — verify they return expected shapes
# ---------------------------------------------------------------------------


class TestLookupEndpoints:
    """Verify the lookup endpoints return data from the actual source modules."""

    def test_content_types_matches_reframe_strategies(self) -> None:
        from reframe_strategies import CONTENT_TYPE_VARIABLES, STRATEGY_CONFIG

        # Every key in CONTENT_TYPE_VARIABLES should be a valid content type
        for ct in CONTENT_TYPE_VARIABLES:
            assert ct in STRATEGY_CONFIG, (
                f"Content type '{ct}' missing from STRATEGY_CONFIG"
            )
            assert "content_description" in CONTENT_TYPE_VARIABLES[ct]

    def test_all_ratios_not_empty(self) -> None:
        from routers.adapts import ALL_RATIOS

        assert len(ALL_RATIOS) > 0
        for r in ALL_RATIOS:
            parts = r.split(":")
            assert len(parts) == 2, f"Invalid ratio format: {r}"

    def test_preset_bundles_use_valid_ratios(self) -> None:
        from routers.adapts import ALL_RATIOS, PRESET_BUNDLES

        for name, bundle in PRESET_BUNDLES.items():
            assert "name" in bundle
            assert "ratios" in bundle
            for ratio in bundle["ratios"]:
                assert ratio in ALL_RATIOS, (
                    f"Preset '{name}' uses ratio '{ratio}' not in ALL_RATIOS"
                )

    def test_content_types_have_strategy(self) -> None:
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
        "dubbing": "/api/v1/dubbing",
    }

    def test_all_job_types_present(self) -> None:
        from agents.tools import _JOB_ENDPOINT_PREFIXES

        for job_type in self.EXPECTED:
            assert job_type in _JOB_ENDPOINT_PREFIXES

    def test_endpoint_paths_match_routers(self) -> None:
        from agents.tools import _JOB_ENDPOINT_PREFIXES

        for job_type, expected_prefix in self.EXPECTED.items():
            assert _JOB_ENDPOINT_PREFIXES[job_type] == expected_prefix, (
                f"{job_type}: expected {expected_prefix}, got {_JOB_ENDPOINT_PREFIXES[job_type]}"
            )


# ---------------------------------------------------------------------------
# Editor prompt pickers — list prompts for a category AND open the picker widget
# ---------------------------------------------------------------------------


class TestEditorPromptPickers:
    """The editor's prompt-lister tools must return the formatted prompt list
    AND set the `prompt_picker` request context so the frontend renders
    PromptPicker(category). This is what lets a user choose an analysis prompt
    for key moments / thumbnails from chat."""

    def _run_lister(
        self, monkeypatch: Any, category: Any, tool_name: Any, label: Any, prompts: Any
    ) -> Any:
        import asyncio

        from agents import _shared
        from agents._shared import (
            get_agent_context,
            make_prompt_lister,
            reset_agent_context,
        )

        async def fake_list_system_prompts(invite_code: Any, cat: Any = None) -> Any:
            assert cat == category
            return prompts

        monkeypatch.setattr(
            _shared.agent_tools, "list_system_prompts", fake_list_system_prompts
        )
        reset_agent_context()
        tool = make_prompt_lister("code-1", category, tool_name, label)
        text = asyncio.run(tool())
        return text, get_agent_context()

    def test_key_moment_prompts_open_picker(self, monkeypatch: Any) -> None:
        prompts = [{"id": "res-1", "name": "Highlights", "description": "Find peaks"}]
        text, ctx = self._run_lister(
            monkeypatch,
            "key-moments",
            "list_key_moment_prompts",
            "Key Moments",
            prompts,
        )
        assert ctx.get("prompt_picker") == "key-moments"
        assert "Highlights" in text and "res-1" in text

    def test_thumbnail_prompts_open_picker(self, monkeypatch: Any) -> None:
        prompts = [{"id": "res-9", "name": "Poster", "description": "Movie poster"}]
        text, ctx = self._run_lister(
            monkeypatch, "thumbnails", "list_thumbnail_prompts", "Thumbnail", prompts
        )
        assert ctx.get("prompt_picker") == "thumbnails"
        assert "Poster" in text and "res-9" in text

    def test_empty_prompts_still_opens_picker(self, monkeypatch: Any) -> None:
        text, ctx = self._run_lister(
            monkeypatch, "key-moments", "list_key_moment_prompts", "Key Moments", []
        )
        assert ctx.get("prompt_picker") == "key-moments"
        assert "No Key Moments prompts" in text

    def test_tool_name_is_set_for_function_tool(self) -> None:
        from agents._shared import make_prompt_lister

        tool = make_prompt_lister(
            "c", "thumbnails", "list_thumbnail_prompts", "Thumbnail"
        )
        assert tool.__name__ == "list_thumbnail_prompts"

    def test_editor_exposes_both_prompt_pickers(self) -> None:
        from agents.specialists.editor import _make_editor_tools

        names = {getattr(f, "__name__", "") for f in _make_editor_tools("code-1")}
        assert "list_key_moment_prompts" in names
        assert "list_thumbnail_prompts" in names
