"""Hybrid (V3) Omni prompt renderer: golden layout plus the A/B construction rules."""

from __future__ import annotations

import re

from hybrid_spec_seed import key_spec, subject
from storygraph.omni.render import render_prompt, render_spec_json
from storygraph.omni.render_hybrid import (
    CLOTHED_DEFAULT,
    SINGLE_TAKE,
    WORD_TARGET,
    render_hybrid,
    word_count,
)
from storygraph.omni.spec import ObjectSpec, ObjectState
from storygraph.omni.text import IdResolver, clause_cut, condense_identity

GOLDEN = """\
Single continuous unbroken shot with no scene cuts. Tactile plasticine claymation with \
visible thumbprints. <FIRST_FRAME> The video starts exactly on the provided first frame. \
Pip lifts the brass key from the Workbench. Pip drops the brass key into the lower drawer.

CHARACTERS:
- Pip <IMAGE_REF_0>: small matte clay pip with a rounded build and bright eyes; wardrobe: \
a snug crimson-red collar sculpted around the neck with a tiny tag; right of frame
- Ava <IMAGE_REF_1>: small matte clay ava with a rounded build and bright eyes; wardrobe: \
fully clothed exactly as in the reference image; left of frame
OBJECTS (each exactly one; never duplicated, never disappears):
- Brass Key <IMAGE_REF_3>: at start on the Workbench, at end inside the lower drawer
- Workbench: stays in place
SETTING: Small Workshop <IMAGE_REF_2>, dusk
CAMERA: Medium close-up, at eye level, 35mm lens. The camera slowly dollies in toward Pip.
DIALOGUE:
- after beat 1, Ava (Hindi, warm low voice): "चाबी मिल गई!"
No other characters. No extra or duplicate props. No text, captions or subtitles. \
No background music."""

_TOKEN_RE = re.compile(
    r"\b(?:MCU|ECU|MS|WS|dolly_in|camera_locked_static|single_continuous_take)\b"
)


def test_golden_layout_is_deterministic() -> None:
    spec = key_spec()
    assert render_hybrid(spec) == GOLDEN
    assert render_prompt(spec, "hybrid") == render_spec_json(spec.render(), "hybrid")


def test_ab_construction_rules() -> None:
    text = render_hybrid(key_spec())
    prose, block = text.split("\n\n", 1)
    assert text.startswith(SINGLE_TAKE)
    assert "momentum" not in prose and not re.search(
        r"\[\d", prose
    )  # no physics, no timecodes
    assert "चाबी" not in prose  # dialogue only in its block, verbatim
    assert re.search(
        r"^- Pip <IMAGE_REF_0>: ", block, re.MULTILINE
    )  # tag right after name
    assert not _TOKEN_RE.search(text)  # plain cinematography words, no machine tokens
    assert block.rstrip().endswith("No background music.")  # guide track: no music
    assert word_count(text) <= WORD_TARGET[1]


def test_word_budget_shortens_identity_but_never_drops_wardrobe() -> None:
    long_ident = " ".join(["tall weathered clay sculpture,"] * 12)
    cast = [
        subject(f"S{i}", f"Hero{i}", f"IMAGE_REF_{i}", identity=long_ident)
        for i in range(1, 6)
    ]
    goals = [
        f"goal number {i} must be visible on screen for the whole take"
        for i in range(6)
    ]
    text = render_hybrid(key_spec(subjects=cast, speech=None, must_achieve=goals))
    assert word_count(text) <= WORD_TARGET[1]
    assert text.count("wardrobe: a snug crimson-red collar") == 5
    assert text.count("goal number") == 1  # retry targets are trimmed before identity


def test_dressed_subject_without_wardrobe_is_explicitly_clothed() -> None:
    ava = subject(
        "S1", "Ava", None, kind="person", wardrobe="None; ", identity="Hand-."
    )
    text = render_hybrid(key_spec(subjects=[ava], speech=None))
    assert f"- Ava: wardrobe: {CLOTHED_DEFAULT}; right of frame" in text
    assert "Hand-" not in text and "None" not in text


def test_clause_cut_never_ends_mid_phrase() -> None:
    collar = "A snug crimson-red plasticine collar sculpted around the neck with a tiny molded matte gold tag"
    assert (
        clause_cut(collar, 12)
        == "A snug crimson-red plasticine collar sculpted around the neck"
    )
    assert clause_cut("Hand-.", 10) == ""


def test_hyphenated_style_phrase_is_removed_whole() -> None:
    desc = (
        "Hand-painted in soft gouache washes. A deep porcelain basin with a chrome tap."
    )
    ident = condense_identity(desc, IdResolver({}), [], 2)
    assert "Hand-" not in ident and "porcelain basin" in ident


def test_off_action_set_dressing_stays_in_spec_but_not_in_prompt() -> None:
    toolbox = ObjectSpec(
        id="O3", name="Red Toolbox", start=ObjectState(where="in_place"), moves=False
    )
    spec = key_spec(objects=[*(key_spec().objects or []), toolbox])
    assert "Red Toolbox" in spec.render()
    assert "Red Toolbox" not in render_hybrid(spec)
    assert "Workbench" in render_hybrid(spec)  # named by a beat, so it is listed
