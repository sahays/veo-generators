"""Hand-built `OmniClipSpec` fixtures for the hybrid prompt-format tests."""

from __future__ import annotations

from storygraph.omni.spec import (
    AudioSpec,
    CameraSpecOut,
    ClipSpec,
    ContinuitySpec,
    ObjectSpec,
    ObjectState,
    OmniClipSpec,
    SettingSpec,
    SpeechSpec,
    StepSpec,
    SubjectSpec,
)


def subject(
    sid: str, name: str, ref: str | None, kind: str = "robot", **kw: object
) -> SubjectSpec:
    base: dict[str, object] = {
        "id": sid,
        "name": name,
        "kind": kind,
        "ref_image": ref,
        "identity": f"Small matte clay {name.lower()} with a rounded build and bright eyes.",
        "wardrobe": "A snug crimson-red collar sculpted around the neck with a tiny tag",
        "screen_pos": "right",
        "framing": "MS",
        "can_speak": True,
        "has_mouth": True,
    }
    return SubjectSpec.model_validate(base | kw)


def key_spec(**overrides: object) -> OmniClipSpec:
    """Pip lifts a key and drops it into a drawer; Ava speaks after beat 1."""
    base: dict[str, object] = {
        "clip": ClipSpec(
            duration_s=8.0,
            aspect="16:9",
            fps=24,
            style="Tactile plasticine claymation with visible thumbprints",
            audio=AudioSpec(),
        ),
        "subjects": [
            subject("S1", "Pip", "IMAGE_REF_0"),
            subject(
                "S2",
                "Ava",
                "IMAGE_REF_1",
                kind="person",
                wardrobe=None,
                screen_pos="left",
            ),
        ],
        "setting": SettingSpec(
            id="L1", name="Small Workshop", ref_image="IMAGE_REF_2", time_of_day="Dusk"
        ),
        "objects": [
            ObjectSpec(
                id="O1",
                name="Brass Key",
                ref_image="IMAGE_REF_3",
                start=ObjectState(where="on the Workbench"),
                end=ObjectState(where="inside the lower drawer"),
                moves=True,
            ),
            ObjectSpec(
                id="O2",
                name="Workbench",
                start=ObjectState(where="in_place"),
                moves=False,
            ),
        ],
        "camera": CameraSpecOut(
            size="MCU", angle="eye", move="dolly_in", lens_mm=35, focus="S1"
        ),
        "continuity": ContinuitySpec(first_frame="FIRST_FRAME"),
        "sequence": [
            StepSpec(
                n=1,
                actor="S1",
                verb="lifts the brass key from the Workbench",
                target="O1",
            ),
            StepSpec(
                n=2,
                actor="S1",
                verb="drops the brass key into the lower drawer, applying gentle forward momentum",
                target="O1",
            ),
        ],
        "speech": [
            SpeechSpec(
                after=1,
                speaker="S2",
                lang="hi",
                text="चाबी मिल गई!",
                voice="warm low voice",
                lipsync=True,
            )
        ],
        "constraints": ["sequence_order_strict", "single_continuous_take"],
    }
    return OmniClipSpec.model_validate(base | overrides)
