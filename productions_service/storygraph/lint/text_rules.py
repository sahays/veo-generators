"""Spec-data lint rules: repeated tokens, vague/truncated object states, consumed end
states and Omni framing limits. Each rule is `LintCase -> list[LintIssue]`."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from typing import Final

from ..omni.spec import ObjectSpec, ObjectState
from ..omni.symbols import Symbols
from ..omni.text import has_repeats
from ..timeline.framing import plan_framing
from ..timeline.placement import condition_as_place, ends_dangling
from .models import CODE_CAMERA_TIGHT, LintCase, LintIssue, issue

_PLACEHOLDER_RE: Final[re.Pattern[str]] = re.compile(
    r"\b[a-z]+_[a-z_]+\b|^\s*(?:in place|unknown|none|null|n/?a|tbd|placeholder|-)\s*$",
    re.IGNORECASE,
)


def _step_texts(case: LintCase) -> Iterator[tuple[int, str]]:
    names = {s.id: s.name for s in case.spec.subjects or []}
    for st in case.spec.sequence or []:
        yield st.n, f"{names.get(st.actor, st.actor)} {st.verb}"
        yield st.n, st.detail or ""
        yield st.n, st.end_state or ""


def rule_repeated_tokens(case: LintCase) -> list[LintIssue]:
    """No adjacent repeated word in rendered step text ('Pip Pip reaches')."""
    hits = {n: text for n, text in _step_texts(case) if has_repeats(text)}
    return [
        issue(
            "REPEATED_TOKEN", case.shot_id, f"step {n} repeats a word: '{t[:60]}'", "S2"
        )
        for n, t in hits.items()
    ]


def _state_defect(state: ObjectState) -> str:
    for text in (state.where or "", state.condition or ""):
        if _PLACEHOLDER_RE.search(text):
            return f"placeholder '{text}'"
        if ends_dangling(text):
            return f"truncated '{text}'"
        if condition_as_place(text):
            return f"condition used as a place '{text}'"
    return ""


def _edges(o: ObjectSpec) -> Iterator[tuple[str, ObjectState]]:
    yield "start", o.start
    if o.end is not None:
        yield "end", o.end


def rule_object_state_text(case: LintCase) -> list[LintIssue]:
    """Object states are concrete plain words: no placeholders, truncation or misused
    conditions."""
    out: list[LintIssue] = []
    for o in case.spec.objects or []:
        for edge, state in _edges(o):
            if defect := _state_defect(state):
                msg = f"{o.id} ({o.name}) {edge} state is {defect}"
                out.append(issue("OBJECT_STATE_TEXT", case.shot_id, msg, "S2"))
    return out


def rule_consumed_end(case: LintCase) -> list[LintIssue]:
    """An object whose lifecycle ends during the clip must not end held or unchanged."""
    if not case.ctx.has_clip:
        return []
    by_id = {o.id: o for o in case.spec.objects or []}
    sym, win = Symbols(case.view), case.ctx.window
    out: list[LintIssue] = []
    for pid in case.view.shot.prop_ids:
        lc = case.ctx.lifecycles.get(pid)
        if lc is None or not lc.alive_at(win.open_at) or lc.alive_at(win.close_at):
            continue
        o = by_id.get(sym.ids.get(pid, ""))
        if o is not None and (o.end is None or o.end.held_by):
            msg = f"{o.name} is consumed in this clip but its end state is not 'gone'"
            out.append(issue("CONSUMED_END_STATE", case.shot_id, msg, "S2"))
    return out


def rule_camera_framing(case: LintCase) -> list[LintIssue]:
    """Tight sizes only for one in-place action on one subject (`FramingPolicy`)."""
    cam = case.view.shot.camera
    chars = case.view.cast_entities.keys()
    decision = plan_framing(cam, case.steps, chars)
    if not decision.widened:
        return []
    msg = (
        f"camera {cam.shot_size} needs one in-place action on one subject; "
        f"render at {decision.camera.shot_size} ({decision.intent})"
    )
    return [LintIssue(CODE_CAMERA_TIGHT, case.shot_id, msg, "S4")]


TEXT_RULES: Final[tuple[Callable[[LintCase], list[LintIssue]], ...]] = (
    rule_repeated_tokens,
    rule_object_state_text,
    rule_consumed_end,
    rule_camera_framing,
)
