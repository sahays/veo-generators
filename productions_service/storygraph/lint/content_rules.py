"""Spec-content lint rules from the prompt-format A/B (`docs/eval/prompt_ab_v1.md` §5).

Failures there traced to spec contents, not format: truncated identity ('Hand-.'), identity
without wardrobe (rendered nudity), object end states that contradict the beats (a key 'held
by Pip' at the end while a beat drops it in a drawer), and holder conflicts. Each rule is
a pure `(spec, shot_id) -> list[LintIssue]` check wrapped as a `LintCase` rule.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Final

from ..omni.render_hybrid import WORD_TARGET, render_hybrid, word_count
from ..omni.spec import ObjectSpec, OmniClipSpec, StepSpec
from ..omni.text import is_truncated
from ..timeline.lifecycle import name_pattern
from ..timeline.placement import ends_dangling
from .models import LintCase, LintIssue, LintSeverity, issue

_DRESSED_KINDS: Final[frozenset[str]] = frozenset({"person", "hybrid"})
_RELEASE_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:drops?|dropped|lands?|landed|falls?|fell|places?|placed|puts?|sets? down|"
    r"releases?|released|toss(?:es)?|tossed|throws?|threw|loses? (?:his|her|its|their) grip|"
    r"hands? (?:it )?(?:to|over)|lays? down|rolls? away)\b",
    re.IGNORECASE,
)
_GRAB_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:picks? up|grabs?|grabbed|takes?|took|lifts?|lifted|catch(?:es)?|caught|"
    r"snatch(?:es)?|holds? up|scoops? up)\b",
    re.IGNORECASE,
)
_STATE_WORD_END_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:the|a|an)\s+(?:closed|open|opened|locked|unlocked|empty|full)$",
    re.IGNORECASE,
)


def identity_issues(spec: OmniClipSpec, sid: str) -> list[LintIssue]:
    """Identity/wardrobe are whole phrases; dressed subjects always carry wardrobe."""
    out: list[LintIssue] = []
    for s in spec.subjects or []:
        for label, text in (("identity", s.identity), ("wardrobe", s.wardrobe)):
            if text and is_truncated(text):
                msg = f"{s.name} {label} is truncated: '{text[-40:]}'"
                out.append(issue("IDENTITY_TRUNCATED", sid, msg, "S4"))
        if s.kind in _DRESSED_KINDS and not s.wardrobe:
            msg = f"{s.name} ({s.kind}) has identity text but no wardrobe"
            out.append(issue("WARDROBE_MISSING", sid, msg, "S4", "warn"))
    for o in spec.objects or []:
        if o.identity and is_truncated(o.identity):
            msg = f"{o.name} identity is truncated: '{o.identity[-40:]}'"
            out.append(issue("IDENTITY_TRUNCATED", sid, msg, "S4"))
    return out


def _beats_naming(obj: ObjectSpec, sequence: list[StepSpec]) -> list[StepSpec]:
    pattern = name_pattern(obj.name)
    return [
        s
        for s in sequence
        if s.target == obj.id
        or pattern.search(" ".join((s.verb, s.detail or "", s.end_state or "")))
    ]


def _changes(obj: ObjectSpec) -> bool:
    return obj.end is not None and obj.end != obj.start


def _end_conflict(obj: ObjectSpec, last: StepSpec) -> tuple[str, LintSeverity]:
    """Why the last beat touching `obj` contradicts its end state ('' when consistent).

    Releasing an object that ends held is an error; grabbing one that ends placed is only
    a warning (grab verbs like 'takes' are ambiguous)."""
    text = " ".join((last.verb, last.detail or ""))
    end = obj.end
    if end is None:
        return "", "warn"
    if end.held_by and _RELEASE_RE.search(text):
        return f"ends held by {end.held_by} but beat {last.n} releases it", "error"
    if not end.held_by and _GRAB_RE.search(text) and not _RELEASE_RE.search(text):
        return (
            f"ends '{end.where}' but beat {last.n} leaves it in {last.actor}'s hands",
            "warn",
        )
    return "", "warn"


def end_state_issues(spec: OmniClipSpec, sid: str) -> list[LintIssue]:
    """An object's end state changes only when a beat causes it, and agrees with that beat."""
    sequence = sorted(spec.sequence or [], key=lambda s: s.n)
    out: list[LintIssue] = []
    for o in (o for o in spec.objects or [] if _changes(o)):
        beats = _beats_naming(o, sequence)
        if not beats:
            msg = f"{o.name} changes state but no beat touches it"
            out.append(issue("END_STATE_WITHOUT_BEAT", sid, msg, "S2", "warn"))
            continue
        why, severity = _end_conflict(o, beats[-1])
        if why:
            msg = f"{o.name} {why}"
            out.append(issue("END_STATE_CONTRADICTS_BEAT", sid, msg, "S2", severity))
    return out


def _holder_issues(spec: OmniClipSpec, sid: str) -> list[LintIssue]:
    holders: dict[str, str] = {}
    out: list[LintIssue] = []
    for s in (s for s in spec.subjects or [] if s.holding):
        if s.holding in holders:
            msg = f"{s.holding} is held by both {holders[s.holding]} and {s.id}"
            out.append(issue("HOLDER_CONFLICT", sid, msg, "S2"))
        holders[s.holding or ""] = s.id
    for o in spec.objects or []:
        start_holder = o.start.held_by
        if o.id in holders and start_holder and start_holder != holders[o.id]:
            msg = f"{o.name} starts held by {start_holder} but {holders[o.id]} holds it"
            out.append(issue("HOLDER_CONFLICT", sid, msg, "S2"))
        for state in (o.start, o.end):
            if state and state.held_by and state.where:
                msg = f"{o.name} is both held by {state.held_by} and '{state.where}'"
                out.append(issue("HOLDER_CONFLICT", sid, msg, "S2"))
    return out


def holder_issues(spec: OmniClipSpec, sid: str) -> list[LintIssue]:
    """Holder facts agree (subject.holding vs object start; no unknown/double holders)."""
    out = _holder_issues(spec, sid)
    for o in spec.objects or []:
        for state in (o.start, o.end):
            where = (state.where or "").strip().rstrip(".") if state else ""
            if where and (_STATE_WORD_END_RE.search(where) or ends_dangling(where)):
                msg = f"{o.name} place '{where}' is not a location"
                out.append(issue("OBJECT_STATE_MALFORMED", sid, msg, "S2", "warn"))
    return out


def budget_issues(spec: OmniClipSpec, sid: str) -> list[LintIssue]:
    """The rendered hybrid prompt stays within the A/B word target (warn only)."""
    words = word_count(render_hybrid(spec))
    if words <= WORD_TARGET[1]:
        return []
    msg = f"hybrid prompt is {words} words (target {WORD_TARGET[0]}-{WORD_TARGET[1]})"
    return [issue("PROMPT_OVER_BUDGET", sid, msg, "S2", "warn")]


SpecCheck = Callable[[OmniClipSpec, str], list[LintIssue]]
_CHECKS: Final[tuple[SpecCheck, ...]] = (
    identity_issues,
    end_state_issues,
    holder_issues,
    budget_issues,
)


def _as_rule(check: SpecCheck) -> Callable[[LintCase], list[LintIssue]]:
    def rule(case: LintCase) -> list[LintIssue]:
        return check(case.spec, case.shot_id)

    rule.__name__ = f"rule_{check.__name__}"
    return rule


CONTENT_RULES: Final[tuple[Callable[[LintCase], list[LintIssue]], ...]] = tuple(
    _as_rule(c) for c in _CHECKS
)
