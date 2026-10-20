"""Per-preset / per-language Responsible-AI prompt softening for Omni video requests.

Rewrites are *not* global: each project resolves a `SafetyProfile` from its visual style
preset and language. Only presets listed in `_PROFILE_BY_PRESET` get story-domain rewrites
(e.g. the Indian mythological epic), and Hindi rules only apply to Hindi-language projects.
The aggressive tier is used solely by the logged fallback ladder after a provider rejection.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

Rule = tuple[re.Pattern[str], str]
_FLAGS = re.IGNORECASE


def _rules(pairs: list[tuple[str, str]]) -> tuple[Rule, ...]:
    return tuple((re.compile(p, _FLAGS), r) for p, r in pairs)


_EPIC_EN: tuple[Rule, ...] = _rules(
    [
        (r"\bmortally\s+wounded\b", "weary and resting"),
        (r"\bwounded\b", "weary"),
        (r"\bdying\b", "resting peacefully"),
        (r"\bdead\b", "resting"),
        (r"\bsacrifice\b", "noble devotion"),
        (r"\bfading\s+with\s+final\s+strength\b", "speaking softly"),
        (r"\bwith\s+fading\s+breath\b", "with gentle voice"),
        (r"\bremaining\s+strength\b", "gentle strength"),
        (r"\bbroken\s+feathers\b", "ruffled feathers"),
        (r"\bfallen\b", "resting"),
        (r"\bweeping\s+gently\b", "speaking with gentle emotion"),
        (r"\bweeping\b", "emotional"),
        (r"\btearful\b", "emotional"),
        (r"\bterrified\b", "startled"),
        (r"\bpanic\b", "surprise"),
        (r"\bstruggles\s+against\b", "steps back from"),
        (r"\babducts?\b", "leads away"),
        (r"\bfled\b", "traveled"),
        (r"\bdemon\s+king\b", "ruler"),
    ]
)
# Hindi: only meaning-preserving softenings. ('दुष्ट'->'रावण' was removed: it renamed a generic
# adjective "wicked" into a specific character and corrupted unrelated dialogue.)
_EPIC_HI: tuple[Rule, ...] = _rules([(r"बलिदान", "समर्पण")])
_EPIC_AGGRESSIVE: tuple[Rule, ...] = _rules(
    [(r"\b(?:grave\s+act|vulture)\b", "gentle")]
)
_GENERIC_AGGRESSIVE: tuple[Rule, ...] = _rules(
    [
        (r"\bAVOID:[^\n]*", ""),
        (r"\b(?:sorrowful|sorrow|grief|grieved|distress|desperate)\b", "gentle"),
    ]
)

_PROFILE_BY_PRESET: dict[str, str] = {"mythological_epic": "indian_epic"}


@dataclass(frozen=True)
class SafetyProfile:
    """Resolved rewrite tables for one project."""

    name: str
    rules: tuple[Rule, ...] = ()
    aggressive_rules: tuple[Rule, ...] = _GENERIC_AGGRESSIVE


def select_safety_profile(visual_style_preset: str, language: str) -> SafetyProfile:
    """Resolve the profile from project meta; unknown presets get no base rewrites."""
    name = _PROFILE_BY_PRESET.get(visual_style_preset or "", "none")
    if name != "indian_epic":
        return SafetyProfile(name="none")
    is_hindi = (language or "").lower().startswith("hi")
    base = _EPIC_EN + (_EPIC_HI if is_hindi else ())
    lang_tag = "hi" if is_hindi else "en"
    return SafetyProfile(
        name=f"{name}:{lang_tag}",
        rules=base,
        aggressive_rules=_GENERIC_AGGRESSIVE + _EPIC_AGGRESSIVE,
    )


def sanitize_prompt(text: str, profile: SafetyProfile, aggressive: bool = False) -> str:
    """Apply the profile's base rules (and aggressive rules when requested)."""
    out = text
    rules = profile.rules + (profile.aggressive_rules if aggressive else ())
    for pattern, replacement in rules:
        out = pattern.sub(replacement, out)
    return out.strip()
