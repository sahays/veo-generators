"""Tests for agent source resolution and specialist tool contracts."""

from typing import Any

# ---------------------------------------------------------------------------
# Source resolution — turn a production/upload reference into a gs:// URI
# (prevents the agent passing a bare production ID as the video, which made
#  the model return an opaque 500 INTERNAL).
# ---------------------------------------------------------------------------


class TestResolveSourceUri:
    def _run(self, monkeypatch: Any, ref: Any, prods: Any, ups: Any) -> Any:
        import asyncio

        from agents import _shared
        from agents._shared import resolve_source_uri

        async def fake_api_call(
            method: Any, path: Any, invite_code: Any, **kwargs: Any
        ) -> Any:
            if "productions" in path:
                return prods
            if "uploads" in path:
                return ups
            return {}

        monkeypatch.setattr(_shared, "api_call", fake_api_call)
        return asyncio.run(resolve_source_uri("code", ref))

    def test_passes_through_gs_uri(self, monkeypatch: Any) -> None:
        assert self._run(monkeypatch, "gs://b/v.mp4", [], []) == "gs://b/v.mp4"

    def test_resolves_production_id_to_final_video(self, monkeypatch: Any) -> None:
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

    def test_resolves_production_by_name_case_insensitive(
        self, monkeypatch: Any
    ) -> None:
        prods = [{"id": "p-1", "name": "My Trailer", "final_video_url": "gs://b/x.mp4"}]
        assert self._run(monkeypatch, "my trailer", prods, []) == "gs://b/x.mp4"

    def test_resolves_upload_by_filename(self, monkeypatch: Any) -> None:
        ups = [
            {
                "id": "u-1",
                "filename": "clip.mp4",
                "display_name": "Clip",
                "gcs_uri": "gs://b/clip.mp4",
            }
        ]
        assert self._run(monkeypatch, "clip.mp4", [], ups) == "gs://b/clip.mp4"

    def test_unmatched_returns_none(self, monkeypatch: Any) -> None:
        assert self._run(monkeypatch, "p-unknown", [], []) is None

    def _run_image(self, monkeypatch: Any, ref: Any, images: Any) -> Any:
        import asyncio

        from agents import _shared
        from agents._shared import resolve_source_uri

        async def fake_api_call(
            method: Any, path: Any, invite_code: Any, **kwargs: Any
        ) -> Any:
            assert "/adapts/sources/uploads" in path  # image kind never hits videos
            return images

        monkeypatch.setattr(_shared, "api_call", fake_api_call)
        return asyncio.run(resolve_source_uri("code", ref, kind="image"))

    def test_image_kind_resolves_image_upload(self, monkeypatch: Any) -> None:
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

    def test_image_kind_passes_through_gs_uri(self, monkeypatch: Any) -> None:
        # gs:// short-circuits before any API call
        assert self._run_image(monkeypatch, "gs://b/i.png", []) == "gs://b/i.png"

    def test_image_kind_unmatched_returns_none(self, monkeypatch: Any) -> None:
        assert self._run_image(monkeypatch, "p-lqnjjvyt", []) is None


class TestEditorProposeResolvesSource:
    """propose_* must resolve a reference to gs:// or open the picker — never
    forward a bare id to the job (which 500s the model)."""

    def test_thumbnails_opens_picker_on_unmatched_ref(self, monkeypatch: Any) -> None:
        import asyncio

        from agents import _shared
        from agents._shared import get_agent_context, reset_agent_context
        from agents.specialists import editor as editor_mod

        async def fake_api_call(
            method: Any, path: Any, invite_code: Any, **kwargs: Any
        ) -> Any:
            return []  # nothing matches

        monkeypatch.setattr(_shared, "api_call", fake_api_call)
        reset_agent_context()
        tools = {f.__name__: f for f in editor_mod._make_editor_tools("code")}
        msg = asyncio.run(tools["propose_thumbnails"]("p-lqnjjvyt", "res-1"))
        ctx = get_agent_context()
        assert "selector" in msg.lower()
        assert ctx.get("source_picker") is True
        assert "confirmation" not in ctx

    def test_thumbnails_resolves_production_id(self, monkeypatch: Any) -> None:
        import asyncio

        from agents import _shared
        from agents._shared import get_agent_context, reset_agent_context
        from agents.specialists import editor as editor_mod

        prods = [{"id": "p-9", "name": "Trailer", "final_video_url": "gs://b/f.mp4"}]

        async def fake_api_call(
            method: Any, path: Any, invite_code: Any, **kwargs: Any
        ) -> Any:
            if "productions" in path:
                return prods
            if "/system/resources" in path:
                return [{"id": "res-1", "name": "Poster"}]
            return []

        monkeypatch.setattr(_shared, "api_call", fake_api_call)

        # resolve_prompt_name (called by propose) goes through agent_tools, stub it
        async def fake_list_prompts(invite_code: Any, category: Any = None) -> Any:
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

    def test_adapts_resolves_image_and_never_queries_videos(
        self, monkeypatch: Any
    ) -> None:
        import asyncio

        from agents import _shared
        from agents._shared import get_agent_context, reset_agent_context
        from agents.specialists import marketer as marketer_mod

        images = [
            {"id": "img-1", "display_name": "Poster", "gcs_uri": "gs://b/poster.png"}
        ]

        async def fake_api_call(
            method: Any, path: Any, invite_code: Any, **kwargs: Any
        ) -> Any:
            # Image resolution must only touch the adapts image catalog.
            assert "productions" not in path and "/promo/" not in path
            if "/adapts/sources/uploads" in path:
                return images
            return []

        async def fake_aspect_ratios(invite_code: Any) -> Any:
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

    def test_adapts_opens_image_picker_on_unmatched_ref(self, monkeypatch: Any) -> None:
        import asyncio

        from agents import _shared
        from agents._shared import get_agent_context, reset_agent_context
        from agents.specialists import marketer as marketer_mod

        async def fake_api_call(
            method: Any, path: Any, invite_code: Any, **kwargs: Any
        ) -> Any:
            return []  # no images match

        monkeypatch.setattr(_shared, "api_call", fake_api_call)
        reset_agent_context()
        tools = {f.__name__: f for f in marketer_mod._make_marketer_tools("code")}
        msg = asyncio.run(tools["propose_adapts"]("p-lqnjjvyt", ["1:1"]))
        ctx = get_agent_context()
        assert "image selector" in msg.lower()
        assert ctx.get("source_picker") == "image"
        assert "confirmation" not in ctx

    def test_marketer_exposes_image_picker_tool(self) -> None:
        from agents.specialists.marketer import _make_marketer_tools

        names = {getattr(f, "__name__", "") for f in _make_marketer_tools("code")}
        assert "list_available_images" in names


class TestFeatureIsolatedAgentHierarchy:
    """Verify the 9-agent ADK topology (1 pure router + 8 feature specialists, excluding Avatars)."""

    def test_orchestrator_is_pure_router_with_8_feature_specialists(
        self, monkeypatch: Any
    ) -> None:
        from google.adk.models.google_llm import Gemini
        from agents import _shared
        from agents.factory import create_orchestrator

        monkeypatch.setattr(
            _shared,
            "create_model",
            lambda tier="router": Gemini(model=_shared.resolve_tier_model_id(tier)),
        )
        orchestrator = create_orchestrator("code-test")
        assert orchestrator.name == "Aanya"
        assert len(orchestrator.tools) == 0

        sub_names = [a.name for a in orchestrator.sub_agents]
        assert sub_names == [
            "productions_agent",
            "reframe_agent",
            "key_moments_agent",
            "thumbnails_agent",
            "promo_agent",
            "adapts_agent",
            "dubbing_agent",
            "finops_agent",
        ]
        assert "avatars_agent" not in sub_names

    def test_model_tiers_match_responsibilities(self) -> None:
        from agents._shared import resolve_tier_model_id

        assert resolve_tier_model_id("router") == "gemini-3.5-flash-lite"
        assert resolve_tier_model_id("finops") == "gemini-3.5-flash-lite"
        assert resolve_tier_model_id("specialist") == "gemini-3.8-flash"
        assert resolve_tier_model_id("creative") == "gemini-3.8-flash"


class TestDubbingAgentTools:
    """Verify dubbing_agent tools and A2UI job_proposal payload."""

    def test_propose_dubbing_populates_a2ui_and_confirmation(
        self, monkeypatch: Any
    ) -> None:
        import asyncio

        from agents import _shared
        from agents._shared import get_agent_context, reset_agent_context
        from agents.specialists import dubbing as dubbing_mod

        prods = [{"id": "p-1", "name": "Demo", "final_video_url": "gs://b/demo.mp4"}]

        async def fake_api_call(
            method: Any, path: Any, invite_code: Any, **kwargs: Any
        ) -> Any:
            if "productions" in path:
                return prods
            return []

        async def fake_langs(invite_code: Any) -> Any:
            return [
                {"code": "es-US", "label": "Spanish (US)"},
                {"code": "hi-IN", "label": "Hindi"},
            ]

        monkeypatch.setattr(_shared, "api_call", fake_api_call)
        monkeypatch.setattr(
            dubbing_mod.agent_tools, "list_dubbing_languages", fake_langs
        )
        reset_agent_context()
        tools = {f.__name__: f for f in dubbing_mod._make_dubbing_tools("code")}
        asyncio.run(tools["propose_dubbing"]("p-1", ["es-US", "hi-IN"], "demo.mp4"))
        ctx = get_agent_context()
        assert ctx["confirmation"]["job_type"] == "dubbing"
        assert ctx["confirmation"]["params"]["gcs_uri"] == "gs://b/demo.mp4"
        assert ctx["confirmation"]["params"]["target_languages"] == ["es-US", "hi-IN"]
        assert ctx["a2ui"]["kind"] == "job_proposal"


class TestFinOpsAgentTools:
    """Verify finops_agent exposes pricing, models, and uploads tools."""

    def test_finops_exposes_all_7_tools(self) -> None:
        from agents.specialists.finops import make_finops_tools

        names = {getattr(f, "__name__", "") for f in make_finops_tools("code")}
        assert names == {
            "get_pricing_rates",
            "get_feature_services",
            "estimate_cost",
            "get_job_cost",
            "list_recent_jobs",
            "list_registered_models",
            "list_uploaded_assets",
        }

    def test_sanitize_markdown_response_strips_html_br_in_tables(self) -> None:
        from agents._shared import sanitize_markdown_response

        raw = (
            "| Feature | Services |\n"
            "|---|---|\n"
            "| Productions | • Gemini Nano Banana 2.1<br>• Gemini Omni 1.1 Flash<br>• Cloud Transcoder HD |\n"
            "Line 1<br/>Line 2"
        )
        cleaned = sanitize_markdown_response(raw)
        assert "<br" not in cleaned
        assert (
            "| Productions | Gemini Nano Banana 2.1; Gemini Omni 1.1 Flash; Cloud Transcoder HD |"
            in cleaned
        )
        assert "Line 1\nLine 2" in cleaned

    def test_create_and_get_shared_chat(self, monkeypatch: Any) -> None:
        import asyncio
        from types import SimpleNamespace
        from routers import chat as chat_router

        monkeypatch.setattr(chat_router.deps, "firestore_svc", None)
        req = SimpleNamespace(state=SimpleNamespace(invite_code="test-code"))
        body = chat_router.ShareChatRequest(
            messages=[
                chat_router.SharedChatItem(role="user", content="List orientations"),
                chat_router.SharedChatItem(
                    role="model",
                    content="Here is 1 job",
                    agent="reframe_agent",
                    latency_ms=1420,
                ),
            ]
        )
        res = asyncio.run(chat_router.create_shared_chat(body, req))
        assert res["id"].startswith("sh-")
        assert res["title"] == "List orientations"

        fetched = asyncio.run(chat_router.get_shared_chat(res["id"]))
        assert fetched["id"] == res["id"]
        assert len(fetched["messages"]) == 2
        assert fetched["messages"][1]["latency_ms"] == 1420
