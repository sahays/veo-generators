"""Spec lint rules. Each rule is `LintCase -> list[LintIssue]` and checks one invariant."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Final

from ..clips.limits import (
    CLIP_LIMITS,
    camera_follows_locomotion,
    count_spoken_words,
)
from ..omni.props import ABSENT_AT_START, CONSUMED, located_in
from ..omni.spec import ObjectSpec, ObjectState, OmniClipSpec
from ..omni.symbols import Symbols
from ..timeline.handling import head_noun, step_text
from ..timeline.locomotion import is_key_action, step_locomotion
from .content_rules import CONTENT_RULES
from .models import LintCase, LintIssue, issue
from .text_rules import TEXT_RULES

MAX_KEY_ACTIONS: Final[int] = CLIP_LIMITS.max_key_actions
MAX_SPOKEN_WORDS: Final[int] = CLIP_LIMITS.max_spoken_words
_SYMBOL_RE: Final[re.Pattern[str]] = re.compile(r"^[SOL]\d+$")
_RAW_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:obj|char|loc|prop|ast|shot|scn|evt|app|dlg|comp)_[A-Za-z0-9_]+\b"
)
_RAW_LABEL_RE: Final[re.Pattern[str]] = re.compile(
    r'"wardrobe":"default"', re.IGNORECASE
)
_APPROACH_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:trots?|walks?|runs?|scurr\w*|dash\w*|hurr\w*|comes?|goes|moves?|steps?)\s+"
    r"(?:over|up)?\s*(?:to|toward|towards)\b|\bapproach\w*",
    re.IGNORECASE,
)
_ADJACENT_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:beside|next to|adjacent|right by)\b", re.IGNORECASE
)
_PREPOSITIONS: Final[frozenset[str]] = frozenset(
    {"on", "in", "under", "beside", "behind", "inside", "near", "at", "by", "atop"}
)
_ARTICLE_RE: Final[re.Pattern[str]] = re.compile(r"\b(?:the|a|an)\b|[^\w\s]")

Rule = Callable[[LintCase], list[LintIssue]]


def rule_references(case: LintCase) -> list[LintIssue]:
    """Every sequence target / speaker / held object resolves to a listed symbol."""
    spec, sid = case.spec, case.shot_id
    objects = {o.id for o in spec.objects or []}
    subjects = {s.id for s in spec.subjects or []}
    out: list[LintIssue] = []
    for st in spec.sequence or []:
        if st.target and not _SYMBOL_RE.match(st.target):
            out.append(
                issue(
                    "UNKNOWN_TARGET",
                    sid,
                    f"step {st.n} targets unknown entity '{st.target}'",
                    "S2",
                )
            )
        elif st.target and st.target.startswith("O") and st.target not in objects:
            out.append(
                issue(
                    "UNLISTED_OBJECT",
                    sid,
                    f"step {st.n} targets {st.target} which is not listed",
                    "S2",
                )
            )
    out += [
        issue(
            "UNLISTED_SPEAKER",
            sid,
            f"speech speaker {s.speaker} is not a subject",
            "S2",
        )
        for s in spec.speech or []
        if s.speaker not in subjects
    ]
    out += [
        issue(
            "HELD_OBJECT_UNLISTED",
            sid,
            f"{s.name} holds {s.holding}, which is not a listed object",
            "S2",
        )
        for s in spec.subjects or []
        if s.holding and s.holding not in objects
    ]
    return out


def rule_object_starts(case: LintCase) -> list[LintIssue]:
    """Every listed object has a concrete start (a place or a holder)."""
    return [
        issue(
            "OBJECT_NO_START",
            case.shot_id,
            f"object {o.id} ({o.name}) has no start state",
            "S2",
        )
        for o in case.spec.objects or []
        if not (o.start.held_by or (o.start.where or "").strip())
    ]


def rule_lifecycle(case: LintCase) -> list[LintIssue]:
    """No object outside its lifecycle (e.g. a consumed object in a later clip)."""
    if not case.ctx.has_clip:
        return []
    win = case.ctx.window
    return [
        issue(
            "OBJECT_OUTSIDE_LIFECYCLE",
            case.shot_id,
            f"object '{pid}' does not exist during this clip",
            "S2",
        )
        for pid in case.view.shot.prop_ids
        if (lc := case.ctx.lifecycles.get(pid)) is not None and not lc.alive_during(win)
    ]


def rule_text_hygiene(case: LintCase) -> list[LintIssue]:
    """No raw graph ids / state labels in the spec; no empty identity text."""
    sid, spec = case.shot_id, case.spec
    out: list[LintIssue] = []
    seq_text = " ".join(s.model_dump_json() for s in spec.sequence or [])
    if _RAW_ID_RE.search(seq_text):
        out.append(
            issue(
                "RAW_ID_IN_SEQUENCE",
                sid,
                f"raw id '{_RAW_ID_RE.search(seq_text).group(0)}' in sequence",
                "S2",
            )
        )  # type: ignore[union-attr]
    rest = spec.model_copy(update={"sequence": None}).render()
    if hit := _RAW_ID_RE.search(rest) or _RAW_LABEL_RE.search(rest):
        out.append(
            issue("RAW_ID_IN_SPEC", sid, f"raw id/label '{hit.group(0)}' in spec", "S4")
        )
    named = [*(spec.subjects or []), *(spec.objects or [])]
    out += [
        issue("EMPTY_IDENTITY", sid, f"{e.id} ({e.name}) has no identity text", "S4")
        for e in named
        if not re.search(r"[A-Za-z]", e.identity or "")
    ]
    return out


def rule_camera(case: LintCase) -> list[LintIssue]:
    """Main-verb locomotion needs a camera that can follow it (`LocomotionCameraPolicy`)."""
    cam = case.spec.camera
    hit = next((h for s in case.steps if (h := step_locomotion(s))), None)
    if hit is None or camera_follows_locomotion(cam.size, cam.move):
        return []
    msg = f"camera {cam.size}/{cam.move} cannot follow locomotion '{hit.clause[:60]}'"
    return [issue("CAMERA_MOVEMENT", case.shot_id, msg, "S4")]


def rule_load(case: LintCase) -> list[LintIssue]:
    """Key-action / spoken-word caps (`CLIP_LIMITS`); speech lands before the final step."""
    sid, spec = case.shot_id, case.spec
    key = [s for s in case.steps if is_key_action(s)]
    out: list[LintIssue] = []
    if len(key) > MAX_KEY_ACTIONS:
        out.append(
            issue(
                "TOO_MANY_ACTIONS",
                sid,
                f"{len(key)} key actions (max {MAX_KEY_ACTIONS})",
                "S2",
            )
        )
    words = sum(count_spoken_words(s.text) for s in spec.speech or [])
    if words > MAX_SPOKEN_WORDS:
        out.append(
            issue(
                "TOO_MANY_WORDS",
                sid,
                f"{words} spoken words (max {MAX_SPOKEN_WORDS})",
                "S2",
            )
        )
    n = len(spec.sequence or [])
    out += [
        issue(
            "SPEECH_AFTER_LAST_STEP",
            sid,
            f"speech by {s.speaker} anchored after step {s.after} of {n}",
            "S2",
        )
        for s in spec.speech or []
        if n and s.after is not None and s.after >= n
    ]
    return out


def rule_adjacency(case: LintCase) -> list[LintIssue]:
    """No 'moves toward X' when the actor already starts beside X."""
    sym = Symbols(case.view)
    out: list[LintIssue] = []
    for st in case.steps:
        if not (
            st.target_id in case.view.cast_entities
            and _APPROACH_RE.search(step_text(st))
        ):
            continue
        where = case.view.cast_states.get(st.actor_id, {}).get("sub_location", "")
        target = sym.name(st.target_id or "")
        if _ADJACENT_RE.search(where) and target.lower() in where.lower():
            msg = f"{sym.name(st.actor_id)} moves toward {target} but already starts '{where}'"
            out.append(issue("ALREADY_ADJACENT", case.shot_id, msg, "S2"))
    return out


def _norm(text: str | None) -> str:
    return " ".join(
        _ARTICLE_RE.sub(" ", (text or "").lower().replace("_", " ")).split()
    )


def _edge(o: ObjectSpec, spec: OmniClipSpec, closing: bool) -> tuple[str, str]:
    state: ObjectState = (o.end or o.start) if closing else o.start
    names = {s.id: s.name for s in spec.subjects or []}
    return names.get(state.held_by or "", state.held_by or ""), _norm(state.where)


def _place_key(place: str) -> tuple[str, str]:
    """(leading preposition, head noun): 'on low countertop' == 'on countertop'."""
    first = place.split(" ", 1)[0]
    return (first if first in _PREPOSITIONS else "", head_noun(place))


def _mismatch(prev: tuple[str, str], cur: tuple[str, str], room: str) -> bool:
    """Holder or place differs; room-level fallbacks ('in the Kitchen') match anything."""
    if prev[0] or cur[0]:
        return prev[0] != cur[0]
    loose = {"", "in place", _norm(ABSENT_AT_START), _norm(CONSUMED), room}
    if prev[1] in loose or cur[1] in loose:
        return False
    return _place_key(prev[1]) != _place_key(cur[1])


def rule_continuity(case: LintCase) -> list[LintIssue]:
    """Each object's start equals its closing state in the previous clip of the scene."""
    if case.prev_spec is None:
        return []
    prev = {o.name: o for o in case.prev_spec.objects or []}
    room = _norm(located_in(case.view.location.canonical_name))
    out: list[LintIssue] = []
    for o in case.spec.objects or []:
        before = prev.get(o.name)
        if before is None:
            continue
        p, c = _edge(before, case.prev_spec, True), _edge(o, case.spec, False)
        if _mismatch(p, c, room):
            msg = f"{o.name} starts {c} but the previous clip ends {p}"
            out.append(issue("CONTINUITY_BREAK", case.shot_id, msg, "S2"))
    return out


RULES: Final[tuple[Rule, ...]] = (
    rule_references,
    rule_object_starts,
    rule_lifecycle,
    rule_text_hygiene,
    rule_camera,
    rule_load,
    rule_adjacency,
    rule_continuity,
    *TEXT_RULES,
    *CONTENT_RULES,
)
