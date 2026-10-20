"""Story beats: comparable text units (events, scenes, clips, lines) extracted from the graph.

A beat's text is verb + object + dialogue (clips) or the authored summary/line (events,
scenes, lines). Beats explicitly marked as a callback (`callback` in the event summary,
scene summary, or dialogue `delivery`) are exempt from duplicate detection.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ..repo import Repo
from ..schema import DialogueLine, InteractionStep, Scene
from .text import content_tokens

_CALLBACK_MARK = "callback"


class BeatKind(StrEnum):
    EVENT = "event"
    SCENE = "scene"
    CLIP = "clip"
    LINE = "line"


@dataclass(frozen=True)
class Beat:
    """One comparable story unit; `scene_index` orders original vs. repeat."""

    kind: BeatKind
    node_id: str
    scene_id: str
    scene_index: int
    text: str
    tokens: frozenset[str]
    callback: bool


def _beat(kind: BeatKind, node_id: str, scene: Scene, text: str, mark: str) -> Beat:
    return Beat(
        kind=kind,
        node_id=node_id,
        scene_id=scene.id,
        scene_index=scene.index,
        text=text,
        tokens=content_tokens(text),
        callback=_CALLBACK_MARK in mark.lower(),
    )


def _step_text(step: InteractionStep) -> str:
    """Verb + object + action clause of one screenplay step."""
    verb = step.action_verb if step.action_verb != "acts" else step.verb
    return f"{verb} {step.target_id or ''} {step.action or step.description}"


def collect_story_beats(repo: Repo) -> list[Beat]:
    """S1 beats: one per Event summary and one per Scene summary."""
    scenes = {s.id: s for s in repo.list_scenes()}
    beats = [
        _beat(BeatKind.SCENE, s.id, s, s.summary, s.summary)
        for s in scenes.values()
        if s.summary
    ]
    for ev in repo.list_events():
        scene = scenes.get(ev.scene_id)
        if scene is not None:
            beats.append(_beat(BeatKind.EVENT, ev.id, scene, ev.summary, ev.summary))
    return beats


def _clip_beats(scene: Scene, lines: dict[str, DialogueLine]) -> list[Beat]:
    steps = {s.step_index: s for s in scene.interaction_steps}
    out: list[Beat] = []
    for clip in scene.clips:
        parts = [_step_text(steps[i]) for i in clip.step_indices if i in steps]
        said = [lines[lid].text for lid in clip.dialogue_line_ids if lid in lines]
        marks = " ".join(
            lines[lid].delivery for lid in clip.dialogue_line_ids if lid in lines
        )
        node_id = f"{scene.id}#clip{clip.clip_index}"
        out.append(_beat(BeatKind.CLIP, node_id, scene, " ".join(parts + said), marks))
    return out


def collect_script_beats(repo: Repo, scene_ids: set[str] | None = None) -> list[Beat]:
    """S2 beats: one per screenwriter clip (verb+object+dialogue) and one per dialogue line."""
    scenes = [s for s in repo.list_scenes() if scene_ids is None or s.id in scene_ids]
    by_id = {s.id: s for s in scenes}
    lines = [ln for ln in repo.list_dialogue() if ln.scene_id in by_id]
    line_map = {ln.id: ln for ln in lines}
    beats = [
        _beat(BeatKind.LINE, ln.id, by_id[ln.scene_id], ln.text, ln.delivery)
        for ln in lines
    ]
    for scene in scenes:
        beats.extend(_clip_beats(scene, line_map))
    return beats
