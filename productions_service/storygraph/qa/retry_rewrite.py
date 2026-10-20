"""Rewrite critic failures into positive, target-state retry instructions.

Video models follow what a prompt *describes*, including descriptions of failures. Retry
feedback therefore never repeats the critic's failure wording. Known artifact flags map to
deterministic target-state templates filled with this shot's actor and prop names; free-text
reasons are classified by keyword into the same templates (or, optionally, rewritten by a cheap
LLM behind `qa.retry_rewrite_llm`). The output is deduplicated, capped, and filtered so that no
instruction contains negative/failure vocabulary.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from ..schema import QAReport
from ..timeline.handling import is_holdable, moved_props
from ..views import ShotView

MAX_INSTRUCTIONS = 4
_ORIGIN_MAX_CHARS = 40
_GENERIC_ACTION = (
    "the action above plays out completely, clearly and in order on screen"
)
BANNED_RE = re.compile(
    r"vanish|disappear|duplicat|\bnever\b|missing|\bno\b|\bnot\b|n't|\bavoid|without"
    r"|remains\s+hanging|\bclone|\bextra\b|\bwrong\b|\bfail",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PropFocus:
    """A prop in the clip: who holds it, its own resting place, and who moves it (if anyone)."""

    name: str
    handler: str | None = None
    origin: str | None = None
    mover: str | None = None


@dataclass(frozen=True)
class RewriteContext:
    """Names from the shot view used to fill target-state templates."""

    actors: tuple[str, ...] = ()
    props: tuple[PropFocus, ...] = ()
    sides: tuple[tuple[str, str], ...] = ()
    actor_keys: dict[str, str] = field(default_factory=dict)


ReasonRewriter = Callable[[str, RewriteContext], str | None]
Template = Callable[[RewriteContext, list[PropFocus], list[str]], list[str]]


def _clip_holders(view: ShotView) -> dict[str, str]:
    """prop_id -> holder name, from the clip's opening/closing holding state only."""
    names = {cid: e.canonical_name for cid, e in view.cast_entities.items()}
    out: dict[str, str] = {}
    for states in (view.cast_states, view.cast_end_states):
        for cid, state in states.items():
            held = state.get("holding")
            if held and cid in names:
                out.setdefault(held, names[cid])
    return out


def _handler_map(view: ShotView) -> dict[str, tuple[str, str | None]]:
    """prop_id -> (holder name, own resting place) for props held in *this* clip.

    Fixtures, liquids and locations never get a holder; looking at a prop is not handling it.
    """
    holders = _clip_holders(view)
    out: dict[str, tuple[str, str | None]] = {}
    for pid, ent in view.prop_entities.items():
        holder = holders.get(pid)
        if not holder or not is_holdable(ent.canonical_name):
            continue
        origin = view.prop_states.get(pid, {}).get("supported_by", "").strip() or None
        out[pid] = (
            holder,
            origin if origin and len(origin) <= _ORIGIN_MAX_CHARS else None,
        )
    return out


def _mover_map(view: ShotView) -> dict[str, str]:
    """prop_id -> actor name for props this clip's steps physically manipulate."""
    names = {cid: e.canonical_name for cid, e in view.cast_entities.items()}
    by_index = {s.step_index: s for s in view.scene.interaction_steps}
    clip = next(
        (c for c in view.scene.clips if c.clip_index == view.shot.clip_index), None
    )
    steps = [by_index[i] for i in (clip.step_indices if clip else []) if i in by_index]
    return {
        pid: names[aid]
        for pid, aid in moved_props(steps).items()
        if pid in view.prop_entities and aid in names
    }


def context_from_view(view: ShotView) -> RewriteContext:
    """Extract actor/prop names, holders, movers and screen sides from a `ShotView`."""
    handlers = _handler_map(view)
    movers = _mover_map(view)
    props = tuple(
        PropFocus(e.canonical_name, *handlers.get(pid, (None, None)), movers.get(pid))
        for pid, e in view.prop_entities.items()
    )
    on_screen = [c for c in view.shot.cast if c.position != "offscreen_voice"]
    actor_keys: dict[str, str] = {}
    sides: list[tuple[str, str]] = []
    for c in on_screen:
        ent = view.cast_entities.get(c.entity_id)
        name = ent.canonical_name if ent else c.entity_id
        sides.append((name, c.position))
        for key in (c.entity_id, name, name.replace(" ", "_")):
            actor_keys[key.lower()] = name
    return RewriteContext(tuple(n for n, _ in sides), props, tuple(sides), actor_keys)


def _mentioned(text: str, names: list[str]) -> list[str]:
    """Names referenced in `text` by full name or head noun (last word)."""
    low = text.lower()

    def _hit(term: str) -> bool:
        return re.search(rf"\b{re.escape(term)}\b", low) is not None

    return [n for n in names if _hit(n.lower()) or _hit(n.lower().split()[-1])]


def _side_phrase(name: str, pos: str) -> str:
    where = {"left": "screen-left", "right": "screen-right", "center": "at center"}
    return f"{name} stays {where.get(pos, f'in the {pos}')}"


# ── Target-state templates (one per artifact flag) ──────────────────────────


def _t_object_present(
    ctx: RewriteContext, ps: list[PropFocus], _a: list[str]
) -> list[str]:
    return [
        f"the {p.name} stays in {p.handler}'s hands and in view for the whole shot"
        if p.handler
        else f"the {p.name} stays visible in its place for the whole shot"
        for p in ps
    ]


def _t_materialized(
    ctx: RewriteContext, _p: list[PropFocus], _a: list[str]
) -> list[str]:
    names = ", ".join(p.name for p in ctx.props)
    base = "every object is present from the first frame or is carried in by hand"
    return [f"{base}; the scene holds exactly these props: {names}" if names else base]


def _t_single_prop(
    ctx: RewriteContext, ps: list[PropFocus], _a: list[str]
) -> list[str]:
    return [
        f"exactly one {p.name}, in {p.handler}'s hands"
        if p.handler
        else f"exactly one {p.name} is in the scene for the whole shot"
        for p in ps
    ]


def _t_single_actor(
    _c: RewriteContext, _p: list[PropFocus], acts: list[str]
) -> list[str]:
    return [
        f"exactly one {a} on screen, a single continuous figure throughout"
        for a in acts
    ]


def _t_actor_visible(
    _c: RewriteContext, _p: list[PropFocus], acts: list[str]
) -> list[str]:
    return [f"{a} is clearly on screen for the whole shot" for a in acts]


def _t_axis(ctx: RewriteContext, _p: list[PropFocus], _a: list[str]) -> list[str]:
    if not ctx.sides:
        return ["each character keeps the same screen side for the whole shot"]
    sides = ", ".join(_side_phrase(n, pos) for n, pos in ctx.sides)
    return [f"the camera stays on one side of the action: {sides}"]


def _t_paths(ctx: RewriteContext, _p: list[PropFocus], acts: list[str]) -> list[str]:
    who = " and ".join(acts) if acts else "every character and object"
    return [f"{who} move along a continuous, visible path between positions"]


def _t_hand_driven(
    ctx: RewriteContext, ps: list[PropFocus], _a: list[str]
) -> list[str]:
    return [
        f"the {p.name} moves only when {p.mover or p.handler or 'a character'}'s hand pushes, "
        "pulls or carries it"
        for p in ps
    ]


def _per_prop(text: str) -> Template:
    def _apply(_c: RewriteContext, ps: list[PropFocus], _a: list[str]) -> list[str]:
        return [text.format(name=p.name) for p in ps]

    return _apply


def _per_actor(text: str) -> Template:
    def _apply(_c: RewriteContext, _p: list[PropFocus], acts: list[str]) -> list[str]:
        return [text.format(name=a) for a in acts]

    return _apply


def _fixed(text: str) -> Template:
    def _apply(_c: RewriteContext, _p: list[PropFocus], _a: list[str]) -> list[str]:
        return [text]

    return _apply


TEMPLATES: dict[str, Template] = {
    "object_vanished": _t_object_present,
    "object_materialized": _t_materialized,
    "duplicate_prop": _t_single_prop,
    "duplicate_character": _t_single_actor,
    "missing_character": _t_actor_visible,
    "spatial_axis_flip": _t_axis,
    "teleportation": _t_paths,
    "self_moving_object": _t_hand_driven,
    "start_frame_bleed": _fixed(
        "the opening frame is already a fully composed moment of the scene, "
        "with motion from frame one"
    ),
    "frozen_frame": _fixed(
        "continuous natural motion from the first frame to the last"
    ),
    "style_drift": _fixed(
        "every frame keeps the one established art style and palette from start to end"
    ),
    "temporal_inconsistency": _fixed(
        "events unfold in one continuous forward timeline, each action following the last"
    ),
    "prop_part_missing": _per_prop(
        "the {name} is whole and intact, with all of its parts, in every frame"
    ),
    "object_state_reversal": _per_prop(
        "the {name} changes state once, forward, and keeps its new state to the end"
    ),
    "prop_mismatch": _per_prop(
        "the {name} matches its reference image in shape, colour and size"
    ),
    "prop_morphing": _per_prop(
        "the {name} keeps the same shape and size in every frame"
    ),
    "prop_inverted": _per_prop("the {name} stays upright in its natural orientation"),
    "floating_object": _per_prop(
        "the {name} rests on a surface or sits in a hand at all times"
    ),
    "character_morphing": _per_actor(
        "{name} keeps the same face, body and outfit in every frame"
    ),
}

# Free-text reason keywords -> flag (first match wins; order matters).
_REASON_RULES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(p, re.IGNORECASE), flag)
    for p, flag in (
        (r"first frame|opening frame|reference sheet", "start_frame_bleed"),
        (
            r"remains?\s+hanging|still\s+(hangs|hanging|on)|\bsecond\b|\btwo\b|duplicat|\bcop(y|ies)\b|clone",
            "duplicate_prop",
        ),
        (r"vanish|disappear|\bgone\b|missing|leaves? the frame", "object_vanished"),
        (
            r"out of nowhere|materiali[sz]|pops? (in|up)|appears? suddenly",
            "object_materialized",
        ),
        (r"by itself|on its own|self[- ]moving", "self_moving_object"),
        (r"teleport|jumps? to", "teleportation"),
        (r"frozen|static|still image", "frozen_frame"),
        (r"flip|mirror|axis|swap", "spatial_axis_flip"),
        (r"revers|back to (its )?original", "object_state_reversal"),
        (r"mismatch|does ?n[o']?t match|different (colou?r|shape)", "prop_mismatch"),
        (r"\bstyle\b|art direction", "style_drift"),
    )
)
_ACTOR_VARIANTS: dict[str, str] = {
    "duplicate_prop": "duplicate_character",
    "object_vanished": "missing_character",
}


def _split_flag(flag: str, ctx: RewriteContext) -> tuple[str, list[str]]:
    """Normalise `duplicate_character_milo` -> ('duplicate_character', ['Milo'])."""
    low = flag.strip().lower()
    for base in ("duplicate_character", "missing_character"):
        if low.startswith(base):
            suffix = low[len(base) :].lstrip("_")
            name = ctx.actor_keys.get(suffix)
            return base, [name] if name else list(ctx.actors[:2])
    return low, []


def _focus(ctx: RewriteContext, text: str) -> tuple[list[PropFocus], list[str]]:
    prop_names = _mentioned(text, [p.name for p in ctx.props])
    props = [p for p in ctx.props if p.name in prop_names]
    if not props:
        props = [p for p in ctx.props if p.handler][:2] or list(ctx.props[:1])
    actors = _mentioned(text, list(ctx.actors)) or list(ctx.actors[:2])
    return props, actors


def _classify_reason(reason: str, ctx: RewriteContext) -> str | None:
    names_props = _mentioned(reason, [p.name for p in ctx.props])
    names_actors = _mentioned(reason, list(ctx.actors))
    for pattern, flag in _REASON_RULES:
        if pattern.search(reason):
            only_actor = names_actors and not names_props
            return _ACTOR_VARIANTS.get(flag, flag) if only_actor else flag
    return None


def _from_flag(flag: str, ctx: RewriteContext, hint_text: str) -> list[str]:
    base, named_actors = _split_flag(flag, ctx)
    template = TEMPLATES.get(base)
    if template is None:
        return []
    props, actors = _focus(ctx, hint_text)
    return template(ctx, props, named_actors or actors)


def _from_reason(
    reason: str, ctx: RewriteContext, llm: ReasonRewriter | None
) -> list[str]:
    flag = _classify_reason(reason, ctx)
    if flag is not None:
        return _from_flag(flag, ctx, reason)
    rewritten = llm(reason, ctx) if llm else None
    return [rewritten] if rewritten else [_GENERIC_ACTION]


def rewrite_retry_feedback(
    report: QAReport, ctx: RewriteContext, llm: ReasonRewriter | None = None
) -> list[str]:
    """Positive target-state instructions for the next attempt (deduped, ≤4, no failure words)."""
    hint = " ".join(report.failure_reasons)
    candidates: list[str] = []
    for reason in report.failure_reasons:
        candidates += _from_reason(reason, ctx, llm)
    for flag in report.artifact_flags:
        candidates += _from_flag(flag, ctx, hint)
    clean = [c.strip() for c in candidates if c.strip() and not BANNED_RE.search(c)]
    return list(dict.fromkeys(clean))[:MAX_INSTRUCTIONS]
