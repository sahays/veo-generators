"""Omni media bindings for keyframe strategies: <FIRST_FRAME>/<LAST_FRAME> and <VIDEO_0>."""

from __future__ import annotations

from dataclasses import replace

from storygraph.adapters.omni.fallback import build_ladder, make_record
from storygraph.adapters.omni.inputs import build_omni_request
from storygraph.adapters.omni.package import RefLabel, RenderPackage
from storygraph.adapters.omni.safety import select_safety_profile
from storygraph.keyframes.animate.strategies import animatic_package, interp_packages
from storygraph.keyframes.plan.models import BeatSpan, PlanInput

_LABELS = (
    RefLabel("gs://b/room.png", "a_room", ("Workshop",), "location"),
    RefLabel("gs://b/pip.png", "a_pip", ("Pip",), "character"),
)
_KF = [f"gs://b/kf_t{t:02d}.png" for t in range(10)]


def _pkg() -> RenderPackage:
    return RenderPackage(
        shot_id="shot_1",
        compiled_prompt="Pip walks.",
        negative_prompt="",
        reference_asset_ids=[lbl.asset_id for lbl in _LABELS],
        reference_uris=[lbl.uri for lbl in _LABELS],
        first_frame_asset_id=None,
        first_frame_uri=None,
        duration_s=9.0,
        aspect_ratio="16:9",
        seed=1,
        package_hash="h",
        reference_labels=_LABELS,
    )


def _inp() -> PlanInput:
    return PlanInput(
        project_id="p",
        scene_id="s",
        shot_id="shot_1",
        clip_index=1,
        duration_s=9.0,
        location_id="loc",
        location_name="Workshop",
        beats=[
            BeatSpan(
                index=0, t_start=0, t_end=4.5, actor_id="char_pip", action="Pip kneels."
            ),
            BeatSpan(
                index=1,
                t_start=4.5,
                t_end=9,
                actor_id="char_pip",
                action="Pip turns the key.",
            ),
        ],
    )


def _header(req_text: str) -> str:
    return req_text.splitlines()[0]


def test_first_last_frames_bound_before_identity_refs() -> None:
    seg = interp_packages(_pkg(), _inp(), _KF, [(3, 6)])[0]
    req = build_omni_request(seg, seg.compiled_prompt, 6)
    head = _header(req.blocks[0]["text"])
    assert head.startswith("[# Sources <FIRST_FRAME>@Image1 <LAST_FRAME>@Image2]")
    assert "<IMAGE_REF_0>@Image3 <IMAGE_REF_1>@Image4" in head
    assert req.image_uris[:2] == (_KF[3], _KF[6])
    assert req.task is None and req.first_frame_bound and req.last_frame_bound
    assert seg.duration_s == 3.0
    # Segment prompt names only the beats overlapping 3-6s.
    assert (
        "Pip kneels." in seg.compiled_prompt
        and "Pip turns the key." in seg.compiled_prompt
    )


def test_last_frame_never_bound_without_first_frame() -> None:
    pkg = replace(_pkg(), last_frame_uri=_KF[9])
    req = build_omni_request(pkg, pkg.compiled_prompt, 6)
    assert "LAST_FRAME" not in req.blocks[0]["text"] and not req.last_frame_bound
    assert _KF[9] not in req.image_uris


def test_video_source_replaces_frames_and_keeps_identity_refs() -> None:
    pkg = replace(
        animatic_package(_pkg(), _inp(), "gs://b/animatic.mp4"), first_frame_uri=_KF[0]
    )
    req = build_omni_request(pkg, pkg.compiled_prompt, 6)
    head = _header(req.blocks[0]["text"])
    assert head.startswith(
        "[# Sources <VIDEO_0>@Video1] [# References <IMAGE_REF_0>@Image1"
    )
    videos = [b for b in req.blocks if b["type"] == "video"]
    assert videos == [
        {"type": "video", "uri": "gs://b/animatic.mp4", "mime_type": "video/mp4"}
    ]
    assert not req.first_frame_bound and _KF[0] not in req.image_uris
    assert req.task is None


def test_fallback_keeps_video_until_text_only_and_records_drop() -> None:
    pkg = animatic_package(_pkg(), _inp(), "gs://b/animatic.mp4")
    profile = select_safety_profile("", "")
    ladder = build_ladder(pkg, profile, 6, "tag")
    assert [s.request.video_uri for s in ladder] == [
        "gs://b/animatic.mp4",
        "gs://b/animatic.mp4",
        None,
    ]
    assert make_record(pkg, "m", profile, ladder, 2, ["x"]).source_video_dropped
    assert not make_record(pkg, "m", profile, ladder, 1, ["x"]).source_video_dropped


def test_fallback_drops_both_frames_together() -> None:
    seg = interp_packages(_pkg(), _inp(), _KF, [(0, 3)])[0]
    ladder = build_ladder(seg, select_safety_profile("", ""), 6, "tag")
    flags = [(s.request.first_frame_bound, s.request.last_frame_bound) for s in ladder]
    assert flags == [(True, True), (False, False), (False, False)]
