"""Sectioned eval prompt: the spec-aware critic rubric plus per-dimension sections.

All extra sections are derived generically from the compiled spec data (subject identity text,
setting look, summary, speech lines) — never from story-specific rules — and carry no attempt
number, so every attempt is judged identically.
"""

from __future__ import annotations

import re
from typing import Any

from ..qa.critic.prompt import build_critic_prompt
from ..qa.critic.spec import CriticSpec
from .contracts import EvalInput

_CLAUSE_RE = re.compile(r"[,;.]\s*")
MAX_FEATURES_PER_SUBJECT = 6

SECTION_RULES = """EVAL SECTIONS (fill every section; observable facts with timestamps only):
- feature_checks: one entry per IDENTITY FEATURE below; present=false only if a frame clearly
  shows the feature differs or is absent while the subject is in view.
- wardrobe_checks: EXACTLY one entry per WARDROBE subject below. List the garments and colours
  seen in each frame; matches_reference=false if any garment/colour differs from the subject's
  REFERENCE image or listed wardrobe; changed_between_frames=true if any garment or colour
  changes between frames (outfit swap, colour shift, garment added/removed). Give timestamps_s.
- temporal: morphing_seen=true if a subject/object changes shape/design between frames.
- spatial: screen positions vs spec screen_pos, 180-degree axis flips, relative scale.
- scene: lighting and time of day vs SETTING LOOK.
- physics_issues: interpenetration, floating, self_moving objects, gravity, missing contact.
- style: style_match 0..1 vs STYLE GUIDE and references.
- script: beats_seen (SCRIPT SUMMARY visibly happens), entrances/exits as scripted,
  unscripted_characters / unscripted_actions (major only), mood_match 0..1 vs SCRIPT MOOD."""


def _subjects(spec: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in spec.get("subjects") or [] if isinstance(s, dict)]


def _subject_name(s: dict[str, Any]) -> str:
    return str(s.get("name") or s.get("id") or "")


def identity_features(spec: dict[str, Any]) -> list[tuple[str, str]]:
    """(subject, feature) pairs split from each subject's spec identity/wardrobe text."""
    out: list[tuple[str, str]] = []
    for s in _subjects(spec):
        text = f"{s.get('identity') or ''}. {s.get('wardrobe') or ''}"
        clauses = [c.strip() for c in _CLAUSE_RE.split(text) if len(c.strip()) > 3]
        out += [(_subject_name(s), c) for c in clauses[:MAX_FEATURES_PER_SUBJECT]]
    return out


def wardrobe_lines(spec: dict[str, Any]) -> list[str]:
    """One expected-wardrobe line per subject (garments + colours, else the REFERENCE)."""
    return [
        f"- {_subject_name(s)}: {s.get('wardrobe') or 'garments and colours of its REFERENCE'}"
        for s in _subjects(spec)
    ]


def _script_lines(spec: dict[str, Any]) -> list[str]:
    look = spec.get("look") if isinstance(spec.get("look"), dict) else {}
    lines = [
        f"SCRIPT SUMMARY: {spec.get('summary') or '(none)'}",
        f"SCRIPT MOOD: {look.get('mood') or '(unspecified)'}",
    ]
    for ln in spec.get("speech") or []:
        if isinstance(ln, dict) and ln.get("text"):
            delivery = f" [{ln['delivery']}]" if ln.get("delivery") else ""
            lines.append(
                f"LINE {ln.get('speaker')} ({ln.get('lang')}){delivery}: {ln['text']}"
            )
    return lines


def _look_lines(spec: dict[str, Any], style_guide: str) -> list[str]:
    setting = spec.get("setting") if isinstance(spec.get("setting"), dict) else {}
    look = spec.get("look") if isinstance(spec.get("look"), dict) else {}
    clip = spec.get("clip") if isinstance(spec.get("clip"), dict) else {}
    return [
        (
            f"SETTING LOOK: time_of_day={setting.get('time_of_day') or 'unspecified'} "
            f"lighting={look.get('lighting') or 'unspecified'}"
        ),
        f"STYLE GUIDE: {style_guide or clip.get('style') or 'match the references'}",
    ]


def build_eval_prompt(
    inp: EvalInput,
    spec: CriticSpec,
    image_labels: list[str],
    has_prev_frame: bool,
    instructions: str,
) -> str:
    """Critic rubric prompt + identity checklist, look, style and script sections."""
    data = inp.spec_dict()
    features = [f"- {who}: {feat}" for who, feat in identity_features(data)]
    base = build_critic_prompt(
        inp.shot_id, spec, image_labels, has_prev_frame, instructions
    )
    return "\n".join(
        [
            base,
            SECTION_RULES,
            "IDENTITY FEATURES:",
            *(features or ["(none)"]),
            "WARDROBE (must match in every frame):",
            *(wardrobe_lines(data) or ["(none)"]),
            *_look_lines(data, inp.style_guide),
            *_script_lines(data),
        ]
    )
