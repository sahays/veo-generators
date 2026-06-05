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


# ---------------------------------------------------------------------------
# Editor prompt pickers — list prompts for a category AND open the picker widget
# ---------------------------------------------------------------------------


class TestEditorPromptPickers:
    """The editor's prompt-lister tools must return the formatted prompt list
    AND set the `prompt_picker` request context so the frontend renders
    PromptPicker(category). This is what lets a user choose an analysis prompt
    for key moments / thumbnails from chat."""

    def _run_lister(self, monkeypatch, category, tool_name, label, prompts):
        import asyncio

        from agents import _shared
        from agents._shared import (
            get_agent_context,
            make_prompt_lister,
            reset_agent_context,
        )

        async def fake_list_system_prompts(invite_code, cat=None):
            assert cat == category
            return prompts

        monkeypatch.setattr(
            _shared.agent_tools, "list_system_prompts", fake_list_system_prompts
        )
        reset_agent_context()
        tool = make_prompt_lister("code-1", category, tool_name, label)
        text = asyncio.run(tool())
        return text, get_agent_context()

    def test_key_moment_prompts_open_picker(self, monkeypatch):
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

    def test_thumbnail_prompts_open_picker(self, monkeypatch):
        prompts = [{"id": "res-9", "name": "Poster", "description": "Movie poster"}]
        text, ctx = self._run_lister(
            monkeypatch, "thumbnails", "list_thumbnail_prompts", "Thumbnail", prompts
        )
        assert ctx.get("prompt_picker") == "thumbnails"
        assert "Poster" in text and "res-9" in text

    def test_empty_prompts_still_opens_picker(self, monkeypatch):
        text, ctx = self._run_lister(
            monkeypatch, "key-moments", "list_key_moment_prompts", "Key Moments", []
        )
        assert ctx.get("prompt_picker") == "key-moments"
        assert "No Key Moments prompts" in text

    def test_tool_name_is_set_for_function_tool(self):
        from agents._shared import make_prompt_lister

        tool = make_prompt_lister(
            "c", "thumbnails", "list_thumbnail_prompts", "Thumbnail"
        )
        assert tool.__name__ == "list_thumbnail_prompts"

    def test_editor_exposes_both_prompt_pickers(self):
        from agents.specialists.editor import _make_editor_tools

        names = {getattr(f, "__name__", "") for f in _make_editor_tools("code-1")}
        assert "list_key_moment_prompts" in names
        assert "list_thumbnail_prompts" in names


# ---------------------------------------------------------------------------
# Source resolution — turn a production/upload reference into a gs:// URI
# (prevents the agent passing a bare production ID as the video, which made
#  the model return an opaque 500 INTERNAL).
# ---------------------------------------------------------------------------


class TestResolveSourceUri:
    def _run(self, monkeypatch, ref, prods, ups):
        import asyncio

        from agents import _shared
        from agents._shared import resolve_source_uri

        async def fake_api_call(method, path, invite_code, **kwargs):
            if "productions" in path:
                return prods
            if "uploads" in path:
                return ups
            return {}

        monkeypatch.setattr(_shared, "api_call", fake_api_call)
        return asyncio.run(resolve_source_uri("code", ref))

    def test_passes_through_gs_uri(self, monkeypatch):
        assert self._run(monkeypatch, "gs://b/v.mp4", [], []) == "gs://b/v.mp4"

    def test_resolves_production_id_to_final_video(self, monkeypatch):
        prods = [
            {
                "id": "p-lqnjjvyt",
                "name": "My Trailer",
                "final_video_url": "gs://b/p-lqnjjvyt/final.mp4",
            }
        ]
        assert (
            self._run(monkeypatch, "p-lqnjjvyt", prods, [])
            == "gs://b/p-lqnjjvyt/final.mp4"
        )

    def test_resolves_production_by_name_case_insensitive(self, monkeypatch):
        prods = [{"id": "p-1", "name": "My Trailer", "final_video_url": "gs://b/x.mp4"}]
        assert self._run(monkeypatch, "my trailer", prods, []) == "gs://b/x.mp4"

    def test_resolves_upload_by_filename(self, monkeypatch):
        ups = [
            {
                "id": "u-1",
                "filename": "clip.mp4",
                "display_name": "Clip",
                "gcs_uri": "gs://b/clip.mp4",
            }
        ]
        assert self._run(monkeypatch, "clip.mp4", [], ups) == "gs://b/clip.mp4"

    def test_unmatched_returns_none(self, monkeypatch):
        assert self._run(monkeypatch, "p-unknown", [], []) is None

    def _run_image(self, monkeypatch, ref, images):
        import asyncio

        from agents import _shared
        from agents._shared import resolve_source_uri

        async def fake_api_call(method, path, invite_code, **kwargs):
            assert "/adapts/sources/uploads" in path  # image kind never hits videos
            return images

        monkeypatch.setattr(_shared, "api_call", fake_api_call)
        return asyncio.run(resolve_source_uri("code", ref, kind="image"))

    def test_image_kind_resolves_image_upload(self, monkeypatch):
        images = [
            {
                "id": "img-1",
                "filename": "poster.png",
                "display_name": "Poster",
                "gcs_uri": "gs://b/poster.png",
                "mime_type": "image/png",
            }
        ]
        assert self._run_image(monkeypatch, "poster", images) == "gs://b/poster.png"

    def test_image_kind_passes_through_gs_uri(self, monkeypatch):
        # gs:// short-circuits before any API call
        assert self._run_image(monkeypatch, "gs://b/i.png", []) == "gs://b/i.png"

    def test_image_kind_unmatched_returns_none(self, monkeypatch):
        assert self._run_image(monkeypatch, "p-lqnjjvyt", []) is None


class TestEditorProposeResolvesSource:
    """propose_* must resolve a reference to gs:// or open the picker — never
    forward a bare id to the job (which 500s the model)."""

    def test_thumbnails_opens_picker_on_unmatched_ref(self, monkeypatch):
        import asyncio

        from agents import _shared
        from agents._shared import get_agent_context, reset_agent_context
        from agents.specialists import editor as editor_mod

        async def fake_api_call(method, path, invite_code, **kwargs):
            return []  # nothing matches

        monkeypatch.setattr(_shared, "api_call", fake_api_call)
        reset_agent_context()
        tools = {f.__name__: f for f in editor_mod._make_editor_tools("code")}
        msg = asyncio.run(tools["propose_thumbnails"]("p-lqnjjvyt", "res-1"))
        ctx = get_agent_context()
        assert "selector" in msg.lower()
        assert ctx.get("source_picker") is True
        assert "confirmation" not in ctx

    def test_thumbnails_resolves_production_id(self, monkeypatch):
        import asyncio

        from agents import _shared
        from agents._shared import get_agent_context, reset_agent_context
        from agents.specialists import editor as editor_mod

        prods = [{"id": "p-9", "name": "Trailer", "final_video_url": "gs://b/f.mp4"}]

        async def fake_api_call(method, path, invite_code, **kwargs):
            if "productions" in path:
                return prods
            if "/system/resources" in path:
                return [{"id": "res-1", "name": "Poster"}]
            return []

        monkeypatch.setattr(_shared, "api_call", fake_api_call)

        # resolve_prompt_name (called by propose) goes through agent_tools, stub it
        async def fake_list_prompts(invite_code, category=None):
            return [{"id": "res-1", "name": "Poster"}]

        monkeypatch.setattr(
            _shared.agent_tools, "list_system_prompts", fake_list_prompts
        )
        reset_agent_context()
        tools = {f.__name__: f for f in editor_mod._make_editor_tools("code")}
        asyncio.run(tools["propose_thumbnails"]("p-9", "res-1"))
        conf = get_agent_context().get("confirmation")
        assert conf is not None
        assert conf["params"]["gcs_uri"] == "gs://b/f.mp4"


class TestMarketerAdaptsImageSource:
    """Adapts resize an IMAGE — the marketer must use the image catalog and the
    image picker, never the video/production sources."""

    def test_adapts_resolves_image_and_never_queries_videos(self, monkeypatch):
        import asyncio

        from agents import _shared
        from agents._shared import get_agent_context, reset_agent_context
        from agents.specialists import marketer as marketer_mod

        images = [
            {"id": "img-1", "display_name": "Poster", "gcs_uri": "gs://b/poster.png"}
        ]

        async def fake_api_call(method, path, invite_code, **kwargs):
            # Image resolution must only touch the adapts image catalog.
            assert "productions" not in path and "/promo/" not in path
            if "/adapts/sources/uploads" in path:
                return images
            return []

        async def fake_aspect_ratios(invite_code):
            return {"ratios": ["1:1", "9:16"], "preset_bundles": {}}

        monkeypatch.setattr(_shared, "api_call", fake_api_call)
        monkeypatch.setattr(
            marketer_mod.agent_tools, "list_aspect_ratios", fake_aspect_ratios
        )
        reset_agent_context()
        tools = {f.__name__: f for f in marketer_mod._make_marketer_tools("code")}
        asyncio.run(tools["propose_adapts"]("Poster", ["1:1", "9:16"]))
        conf = get_agent_context().get("confirmation")
        assert conf is not None
        assert conf["params"]["gcs_uri"] == "gs://b/poster.png"

    def test_adapts_opens_image_picker_on_unmatched_ref(self, monkeypatch):
        import asyncio

        from agents import _shared
        from agents._shared import get_agent_context, reset_agent_context
        from agents.specialists import marketer as marketer_mod

        async def fake_api_call(method, path, invite_code, **kwargs):
            return []  # no images match

        monkeypatch.setattr(_shared, "api_call", fake_api_call)
        reset_agent_context()
        tools = {f.__name__: f for f in marketer_mod._make_marketer_tools("code")}
        msg = asyncio.run(tools["propose_adapts"]("p-lqnjjvyt", ["1:1"]))
        ctx = get_agent_context()
        assert "image selector" in msg.lower()
        assert ctx.get("source_picker") == "image"
        assert "confirmation" not in ctx

    def test_marketer_exposes_image_picker_tool(self):
        from agents.specialists.marketer import _make_marketer_tools

        names = {getattr(f, "__name__", "") for f in _make_marketer_tools("code")}
        assert "list_available_images" in names
