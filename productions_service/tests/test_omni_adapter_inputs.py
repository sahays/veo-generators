"""Omni request assembly: labelled refs, first-frame binding, per-preset safety, logged fallbacks."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import pytest
from storygraph.adapters.gemini_video import GeminiVideoGenerator
from storygraph.adapters.omni.fallback import build_ladder
from storygraph.adapters.omni.inputs import build_omni_request
from storygraph.adapters.omni.package import RefLabel, RenderPackage
from storygraph.adapters.omni.safety import sanitize_prompt, select_safety_profile
from storygraph.config import VideoProviderCfg
from storygraph.omni.spec import (
    AudioSpec,
    CameraSpecOut,
    ClipSpec,
    ContinuitySpec,
    ObjectSpec,
    ObjectState,
    OmniClipSpec,
    SettingSpec,
    SubjectSpec,
)
from storygraph.pipeline.render_stage import _attach_fallback
from storygraph.repo import Repo
from storygraph.schema import GenerationRun, Role

_FF = "gs://b/prev_last.png"
_LABELS = (
    RefLabel("gs://b/towel.png", "a_towel", ("Kitchen Towel",), "prop"),
    RefLabel("gs://b/kitchen.png", "a_kit", ("Kitchen",), "location"),
    RefLabel("gs://b/milo.png", "a_milo", ("Milo",), "character"),
    RefLabel("gs://b/pip.png", "a_pip", ("Pip",), "character", speaking=True),
)


def _pkg(
    first_frame: str | None = _FF,
    labels: tuple[RefLabel, ...] = _LABELS,
    prompt: str = "SHOT: Pip lifts the towel off the peg.",
) -> RenderPackage:
    return RenderPackage(
        shot_id="shot_004_02",
        compiled_prompt=prompt,
        negative_prompt="",
        reference_asset_ids=[lbl.asset_id for lbl in labels],
        reference_uris=[lbl.uri for lbl in labels],
        first_frame_asset_id="a_ff" if first_frame else None,
        first_frame_uri=first_frame,
        duration_s=8.0,
        aspect_ratio="16:9",
        seed=7,
        package_hash="h",
        reference_labels=labels,
        project_id="p-zyt0jprz",
        visual_style_preset="ghibli_handpainted",
        language="hi-IN",
    )


def _images(blocks: list[dict[str, Any]]) -> list[str]:
    return [b["uri"] for b in blocks if b["type"] == "image"]


def test_labels_interleave_and_characters_precede_props() -> None:
    req = build_omni_request(_pkg(), "PROMPT", max_images=6, first_frame_mode="tag")
    assert _images(req.blocks) == [
        _FF,
        "gs://b/pip.png",
        "gs://b/milo.png",
        "gs://b/kitchen.png",
        "gs://b/towel.png",
    ]
    header = req.blocks[0]["text"].splitlines()[0]
    assert header.startswith(
        "[# Sources <FIRST_FRAME>@Image1] [# References <IMAGE_REF_0>@Image2"
    )
    for idx, block in enumerate(req.blocks[1:]):
        assert block["type"] == ("text" if idx % 2 == 0 else "image")
    pip_caption = req.blocks[3]["text"]
    assert pip_caption.startswith("Reference image 2 <IMAGE_REF_0> — Pip identity")
    assert "appearance only, not a frame" in pip_caption
    assert req.task is None and req.first_frame_bound


def test_image_cap_keeps_setting_and_drops_props_before_characters() -> None:
    req = build_omni_request(_pkg(), "PROMPT", max_images=3, first_frame_mode="tag")
    assert _images(req.blocks) == [_FF, "gs://b/pip.png", "gs://b/kitchen.png"]
    req = build_omni_request(_pkg(), "PROMPT", max_images=4, first_frame_mode="tag")
    assert "gs://b/towel.png" not in _images(req.blocks)
    assert _images(req.blocks)[-1] == "gs://b/kitchen.png"


def test_drop_mode_never_sends_last_frame_as_identity_ref() -> None:
    labels = (*_LABELS, RefLabel(_FF, "a_ff", ("prev",), "other"))
    req = build_omni_request(_pkg(labels=labels), "PROMPT", 6, first_frame_mode="drop")
    assert _FF not in _images(req.blocks)
    assert "<FIRST_FRAME>" not in req.blocks[0]["text"]
    assert req.task == "reference_to_video"


def test_safety_rewrites_only_for_epic_preset_and_never_rename_wicked() -> None:
    text = "The dying demon king speaks. बलिदान दुष्ट"
    plain = select_safety_profile("ghibli_handpainted", "hi-IN")
    assert sanitize_prompt(text, plain) == text
    epic_hi = select_safety_profile("mythological_epic", "hi-IN")
    out = sanitize_prompt(text, epic_hi)
    assert "resting peacefully ruler" in out and "समर्पण" in out
    assert "दुष्ट" in out and "रावण" not in out
    epic_en = select_safety_profile("mythological_epic", "en-IN")
    assert "बलिदान" in sanitize_prompt(text, epic_en)


class _FlakyInteractions:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.inputs: list[list[dict[str, Any]]] = []

    def create(self, **kwargs: Any) -> dict[str, str]:
        self.inputs.append(kwargs["input"])
        if len(self.inputs) <= self.failures:
            raise RuntimeError("RAI filter blocked request")
        return {"id": "int_1", "status": "completed"}


class _FakeClient:
    def __init__(self, failures: int) -> None:
        self.interactions = _FlakyInteractions(failures)


def test_fallback_ladder_is_logged_and_recorded(
    caplog: pytest.LogCaptureFixture,
) -> None:
    gen = GeminiVideoGenerator(caps=VideoProviderCfg(max_reference_images=6))
    client = _FakeClient(failures=1)
    with caplog.at_level(logging.WARNING):
        gen._run_ladder(
            client, "gemini-omni-1.1-flash-preview", _pkg(), {"type": "video"}
        )
    assert _images(client.interactions.inputs[1]) == ["gs://b/pip.png"]
    record = gen.pop_fallback("shot_004_02")
    assert record is not None and record.fallback_level == "aggressive_single_ref"
    assert set(record.refs_dropped) == {
        _FF,
        "gs://b/milo.png",
        "gs://b/kitchen.png",
        "gs://b/towel.png",
    }
    assert record.first_frame_dropped and record.project_id == "p-zyt0jprz"
    logged = [r for r in caplog.records if getattr(r, "what", "") == "omni_fallback"]
    assert logged and logged[0].shot_id == "shot_004_02"
    assert gen.pop_fallback("shot_004_02") is None


def test_clean_render_clears_stale_fallback_and_attach_logs(
    tmp_repo: Repo, caplog: pytest.LogCaptureFixture
) -> None:
    gen = GeminiVideoGenerator(caps=VideoProviderCfg(max_reference_images=6))
    gen._run_ladder(_FakeClient(2), "omni", _pkg(), {"type": "video"})
    gen._run_ladder(_FakeClient(0), "omni", _pkg(), {"type": "video"})
    assert gen.pop_fallback("shot_004_02") is None
    run = GenerationRun(
        id="r1",
        created_by=Role.PIPELINE,
        shot_id="shot_004_02",
        attempt=1,
        provider="veo",
        model="omni",
        compiled_prompt="p",
        seed=1,
        package_hash="h",
    )
    fb = {
        "fallback_level": "text_to_video",
        "reasons": ["blocked"],
        "refs_dropped": ["x"],
    }
    with caplog.at_level(logging.WARNING):
        out = _attach_fallback(tmp_repo, run, fb)
    rec = [
        r
        for r in caplog.records
        if getattr(r, "what", "") == "render_fallback_recorded"
    ]
    assert rec and rec[0].fallback_level == "text_to_video" and rec[0].run_id == "r1"
    persisted = "render_fallback" in GenerationRun.model_fields
    assert getattr(out, "render_fallback", None) == (fb if persisted else None)


def _spec_prompt() -> str:
    def subj(sid: str, name: str, ref: str) -> SubjectSpec:
        return SubjectSpec(
            id=sid,
            name=name,
            kind="robot",
            ref_image=ref,
            screen_pos="center",
            framing="MS",
            can_speak=True,
            has_mouth=False,
        )

    return OmniClipSpec(
        clip=ClipSpec(duration_s=8.0, aspect="16:9", fps=24, audio=AudioSpec()),
        subjects=[subj("S1", "Pip", "IMAGE_REF_0"), subj("S2", "Milo", "IMAGE_REF_1")],
        setting=SettingSpec(id="L1", name="Kitchen", ref_image="IMAGE_REF_2"),
        objects=[
            ObjectSpec(
                id="O1",
                name="Kitchen Towel",
                ref_image="IMAGE_REF_3",
                start=ObjectState(where="wall peg"),
                moves=True,
            )
        ],
        camera=CameraSpecOut(size="MS", angle="eye", move="static", lens_mm=35),
        continuity=ContinuitySpec(first_frame="FIRST_FRAME"),
        constraints=["refs_are_identity_only", "first_frame_is_opening_frame"],
    ).render()


def _bound_tokens(spec: OmniClipSpec) -> set[str]:
    items = [*(spec.subjects or []), *(spec.objects or []), spec.setting]
    return {i.ref_image for i in items if i.ref_image}


def test_request_text_is_header_plus_spec_with_no_trailing_prose() -> None:
    req = build_omni_request(_pkg(prompt=_spec_prompt()), _spec_prompt(), 6)
    header, body = req.blocks[0]["text"].split("\n")
    assert header.startswith("[# Sources <FIRST_FRAME>@Image1]")
    assert json.loads(body)["task"] == "render_video_clip"
    assert req.blocks[0]["text"].endswith("}")


def test_every_rung_binds_only_images_it_sends() -> None:
    profile = select_safety_profile("", "")
    ladder = build_ladder(_pkg(prompt=_spec_prompt()), profile, 6, "tag")
    expected = [
        {"IMAGE_REF_0", "IMAGE_REF_1", "IMAGE_REF_2", "IMAGE_REF_3"},
        {"IMAGE_REF_0"},
        set(),
    ]
    for step, want in zip(ladder, expected, strict=True):
        header, body = step.request.blocks[0]["text"].rpartition("\n")[::2]
        spec = OmniClipSpec.model_validate_json(body)
        sent = set(re.findall(r"<(IMAGE_REF_\d+)>@Image", header))
        assert _bound_tokens(spec) == sent == want
        ff_bound = bool(spec.continuity and spec.continuity.first_frame)
        assert ff_bound == step.request.first_frame_bound
        assert ("refs_are_identity_only" in spec.constraints) == bool(want)
    single = OmniClipSpec.model_validate_json(
        ladder[1].request.blocks[0]["text"].split("\n")[-1]
    )
    assert single.subjects and single.subjects[0].ref_image == "IMAGE_REF_0"
    assert (
        single.setting.ref_image is None
        and "first_frame_is_opening_frame" not in single.constraints
    )
