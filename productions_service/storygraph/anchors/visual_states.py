"""Per-state appearances: map graph state text to visual state labels and pick matching looks.

A *visual state* is a condition that changes how an entity looks on screen (wet, spilled,
dirty, broken...). The Design Studio mints one Appearance per visual state
(`Appearance.state_label`), and reference selection attaches the sheet whose label matches the
clip's opening state for that entity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from ..repo import Repo
from ..schema import Appearance, Asset, Status
from ..views import ShotView

# Canonical label -> keywords (first matching label wins; dict order is the precedence).
VISUAL_STATE_VOCAB: Final[dict[str, tuple[str, ...]]] = {
    "broken": ("broken", "shattered", "cracked", "smashed", "snapped"),
    "spilled": ("spilled", "spilt", "knocked over", "tipped over", "overturned"),
    "wet": ("wet", "soaked", "damp", "drenched", "dripping", "soggy"),
    "dirty": ("dirty", "muddy", "stained", "grimy", "smeared"),
    "torn": ("torn", "ripped", "shredded"),
    "burnt": ("burnt", "burned", "scorched", "charred"),
}
VISUAL_STATE_LABELS: Final[frozenset[str]] = frozenset(VISUAL_STATE_VOCAB)

_NEGATION = r"(?<!\bnot )(?<!\bno longer )"
_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = tuple(
    (
        label,
        re.compile(
            _NEGATION + r"\b(?:" + "|".join(re.escape(k) for k in kws) + r")\b",
            re.IGNORECASE,
        ),
    )
    for label, kws in VISUAL_STATE_VOCAB.items()
)


@dataclass(frozen=True)
class StateRef:
    """Appearance + sheet chosen for an entity's opening visual state in one clip."""

    entity_id: str
    label: str
    appearance: Appearance
    asset: Asset


def visual_state_label(text: str) -> str | None:
    """Canonical visual-state label described by `text` (None for neutral/negated text)."""
    if not text:
        return None
    return next((label for label, pat in _PATTERNS if pat.search(text)), None)


def entity_visual_state_labels(repo: Repo, entity_id: str) -> list[str]:
    """Visual states an entity passes through (interaction-step states + injury facts)."""
    texts = [
        txt
        for sc in repo.list_scenes()
        for st in sc.interaction_steps
        if st.target_id == entity_id
        for txt in (st.pre_state, st.post_state)
    ]
    texts += [
        sf.value
        for sf in repo.list_state_facts(entity_id=entity_id)
        if sf.attribute == "injury"
    ]
    labels = {lbl for t in texts if (lbl := visual_state_label(t))}
    return sorted(labels)


def opening_state_text(view: ShotView, entity_id: str) -> str:
    """Opening-state text for `entity_id` in this clip, read from existing view fields.

    Props: `prop_states[id]["opening_state"]` (per-clip, Phase 1) falling back to `pre_state`.
    Characters: the `injury` state fact active at the clip.
    """
    prop = view.prop_states.get(entity_id)
    if prop is not None:
        return prop.get("opening_state") or prop.get("pre_state", "")
    return view.cast_states.get(entity_id, {}).get("injury", "")


def pick_state_appearance(apps: list[Appearance], label: str) -> Appearance | None:
    """Best non-superseded Appearance labelled `label` with a sheet (APPROVED, newest first)."""
    matching = [
        a
        for a in apps
        if a.state_label == label and a.asset_ids and a.status != Status.SUPERSEDED
    ]
    return max(
        matching,
        key=lambda a: (a.status == Status.APPROVED, a.version),
        default=None,
    )


def _state_ref(repo: Repo, view: ShotView, entity_id: str) -> StateRef | None:
    label = visual_state_label(opening_state_text(view, entity_id))
    if label is None:
        return None
    app = pick_state_appearance(repo.list_appearances(entity_id=entity_id), label)
    asset = repo.get_asset(app.asset_ids[-1]) if app else None
    if app is None or asset is None:
        return None
    return StateRef(entity_id, label, app, asset)


def resolve_state_refs(repo: Repo, view: ShotView) -> dict[str, StateRef]:
    """entity_id -> state-matched sheet for every on-screen character and prop in the clip."""
    ids = [c.entity_id for c in view.shot.cast if c.position != "offscreen_voice"]
    ids += list(view.shot.prop_ids)
    refs = {eid: ref for eid in ids if (ref := _state_ref(repo, view, eid))}
    return refs
