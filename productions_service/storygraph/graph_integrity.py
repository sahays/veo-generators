"""Per-production StoryGraph integrity report (typed), run after S5 and exposed in the snapshot.

Finding kinds (all general, story-agnostic):
* `contradiction`      – one Event sets the same (entity, attribute) to two values, or one
                         object is held by two holders at the same time;
* `no_lifecycle`       – an object used by shots/steps has no StateFact (never placed/held);
* `opening_gap`        – a clip opens on a different state than the previous clip of the
                         same scene closed on (an Event between them is played by no clip);
* `cast_location`      – cast opens a clip away from the shot location with no entrance;
* `orphan`             – entity / event / dialogue / appearance referenced by nothing, or
                         pointing at a missing node; state facts with an unknown cause;
* `noop_fact`          – an Event effect restating the current value (dropped on replay);
* `raw_id`             – raw graph ids (char_x, obj_y…) leaked into authored text;
* `implicit_entry`     – (info) cast relocated by the scene-entry rule, not by an Event.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from itertools import pairwise
from typing import Final, Literal

from .repo import Repo
from .schema import (
    EntityType,
    Event,
    Role,
    Shot,
    StageQaIssue,
    StageQaReport,
    StateFact,
    Status,
)
from .timeline.scene_entry import is_scene_entry_cause

_log = logging.getLogger(__name__)
Severity = Literal["error", "warn", "info"]
STAGE: Final[str] = "S5_INTEGRITY"
_RAW_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:char|obj|loc|prop|scn|evt|shot|app|asset)_[a-z0-9_]+\b"
)
_STATE_KEYS: Final[tuple[str, ...]] = ("location", "holding", "state", "wearing")


@dataclass(frozen=True)
class IntegrityFinding:
    """One integrity defect: what kind, on which node, why."""

    kind: str
    node_id: str
    message: str
    severity: Severity = "warn"


@dataclass
class IntegrityReport:
    """Typed per-production report; `counts` is per finding kind."""

    project_id: str
    findings: list[IntegrityFinding] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)

    @property
    def counts(self) -> dict[str, int]:
        return dict(Counter(f.kind for f in self.findings))

    def add(
        self, kind: str, node_id: str, message: str, severity: Severity = "warn"
    ) -> None:
        self.findings.append(IntegrityFinding(kind, node_id, message, severity))

    def to_dict(self) -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "counts": self.counts,
            "stats": self.stats,
            "findings": [asdict(f) for f in self.findings],
        }


class _Facts:
    """`entity -> facts` index with O(k) point-in-time lookups."""

    def __init__(self, facts: list[StateFact]) -> None:
        self.by_entity: dict[str, list[StateFact]] = {}
        for f in facts:
            self.by_entity.setdefault(f.entity_id, []).append(f)

    def at(self, entity_id: str, order: int) -> dict[str, str]:
        return {
            f.attribute: f.value
            for f in self.by_entity.get(entity_id, [])
            if f.valid_from_order <= order
            and (f.valid_to_order is None or order < f.valid_to_order)
        }


def _check_events(rep: IntegrityReport, events: list[Event]) -> None:
    """Contradictory effects within one Event and no-op restatements."""
    current: dict[tuple[str, str], str | None] = {}
    for ev in events:
        seen: dict[tuple[str, str], str | None] = {}
        for eff in ev.effects:
            key = (eff.entity_id, eff.attribute)
            if key in seen and seen[key] != eff.new_value:
                rep.add(
                    "contradiction",
                    ev.id,
                    f"{ev.id} sets {key[0]}.{key[1]} to both '{seen[key]}' and '{eff.new_value}'",
                    "error",
                )
            seen[key] = eff.new_value
            if key in current and current[key] == eff.new_value:
                rep.add(
                    "noop_fact",
                    ev.id,
                    f"{ev.id} restates {key[0]}.{key[1]}='{eff.new_value}'",
                    "info",
                )
        current.update(seen)


def _check_holders(rep: IntegrityReport, facts: list[StateFact]) -> None:
    """An object held by two holders over overlapping intervals."""
    by_obj: dict[str, list[StateFact]] = {}
    for f in facts:
        if f.attribute == "holding" and f.value:
            by_obj.setdefault(f.value, []).append(f)
    for obj, holds in by_obj.items():
        holds.sort(key=lambda f: f.valid_from_order)
        for a, b in pairwise(holds):
            if a.entity_id != b.entity_id and (
                a.valid_to_order is None or b.valid_from_order < a.valid_to_order
            ):
                rep.add(
                    "contradiction",
                    obj,
                    f"'{obj}' held by '{a.entity_id}' and '{b.entity_id}' at order {b.valid_from_order}",
                    "error",
                )


def _check_lifecycles(repo: Repo, rep: IntegrityReport, idx: _Facts) -> None:
    used = {p for s in repo.list_shots() for p in s.prop_ids}
    used |= {
        st.target_id
        for sc in repo.list_scenes()
        for st in sc.interaction_steps
        if st.target_id
    }
    for ent in repo.list_entities(entity_type=EntityType.OBJECT):
        if ent.id in used and ent.id not in idx.by_entity:
            rep.add(
                "no_lifecycle",
                ent.id,
                f"object '{ent.id}' is used but never placed or held (no StateFact)",
            )


def _check_clip_chain(repo: Repo, rep: IntegrityReport, idx: _Facts) -> None:
    """Opening state of clip k must equal closing state of clip k-1 in the same scene."""
    by_scene: dict[str, list[Shot]] = {}
    for sh in repo.list_shots():
        by_scene.setdefault(sh.scene_id, []).append(sh)
    for shots in by_scene.values():
        shots.sort(key=lambda s: (s.story_order, s.index_in_scene))
        for prev, cur in pairwise(shots):
            close = max(
                [
                    prev.story_order,
                    *(
                        e.story_order
                        for i in prev.covers_event_ids
                        if (e := repo.get_event(i))
                    ),
                ]
            )
            opening = cur.story_order - 1 if cur.covers_event_ids else cur.story_order
            ids = {c.entity_id for c in cur.cast} | set(cur.prop_ids)
            for eid in sorted(ids):
                a, b = idx.at(eid, close), idx.at(eid, opening)
                diff = [k for k in _STATE_KEYS if a.get(k) != b.get(k)]
                if diff:
                    rep.add(
                        "opening_gap",
                        cur.id,
                        f"{cur.id} opens with {eid} {diff} != closing of {prev.id} (uncovered Event between)",
                    )


def _check_cast_location(repo: Repo, rep: IntegrityReport, idx: _Facts) -> None:
    for sh in repo.list_shots():
        opening = sh.story_order - 1 if sh.covers_event_ids else sh.story_order
        entering = {
            f.entity_id
            for i in sh.covers_event_ids
            if (ev := repo.get_event(i))
            for f in ev.effects
            if f.attribute == "location" and f.new_value == sh.location_id
        }
        for c in sh.cast:
            loc = idx.at(c.entity_id, opening).get("location")
            if loc and loc != sh.location_id and c.entity_id not in entering:
                rep.add(
                    "cast_location",
                    sh.id,
                    f"{sh.id}: {c.entity_id} opens at '{loc}', shot is at '{sh.location_id}'",
                    "error",
                )


def _check_orphans(repo: Repo, rep: IntegrityReport, events: list[Event]) -> None:
    ents = {e.id: e for e in repo.list_entities()}
    scenes = {s.id: s for s in repo.list_scenes()}
    ev_ids = {e.id for e in events}
    referenced = {p for e in events for p in e.participants}
    referenced |= {f.entity_id for e in events for f in e.effects}
    referenced |= {s.location_id for s in scenes.values()}
    referenced |= {
        x
        for sc in scenes.values()
        for st in sc.interaction_steps
        for x in (st.actor_id, st.target_id)
        if x
    }
    for sh in repo.list_shots():
        referenced |= (
            {c.entity_id for c in sh.cast} | set(sh.prop_ids) | {sh.location_id}
        )
    for d in repo.list_dialogue():
        referenced.add(d.speaker_id)
        if d.scene_id not in scenes or d.speaker_id not in ents:
            rep.add(
                "orphan",
                d.id,
                f"dialogue '{d.id}' points at missing scene/speaker",
                "error",
            )
    for eid in sorted(set(ents) - referenced):
        rep.add(
            "orphan",
            eid,
            f"entity '{eid}' is referenced by no event, step, shot or line",
        )
    for ev in events:
        if ev.scene_id not in scenes:
            rep.add(
                "orphan",
                ev.id,
                f"event '{ev.id}' belongs to missing scene '{ev.scene_id}'",
                "error",
            )
    for app in repo.list_appearances():
        if app.entity_id not in ents:
            rep.add(
                "orphan",
                app.id,
                f"appearance '{app.id}' for missing entity '{app.entity_id}'",
            )
    for f in repo.list_state_facts():
        if (
            not is_scene_entry_cause(f.caused_by_event_id)
            and f.caused_by_event_id not in ev_ids
        ):
            rep.add(
                "orphan",
                f.id,
                f"state fact '{f.id}' caused by unknown event '{f.caused_by_event_id}'",
            )


def _check_raw_ids(repo: Repo, rep: IntegrityReport, events: list[Event]) -> None:
    texts: list[tuple[str, str]] = [(e.id, e.summary) for e in events]
    for sc in repo.list_scenes():
        texts.append((sc.id, sc.summary))
        texts += [
            (sc.id, f"{st.action} {st.post_state}") for st in sc.interaction_steps
        ]
        texts += [(sc.id, c.omni_prompt) for c in sc.clips]
    texts += [(d.id, d.text) for d in repo.list_dialogue()]
    for node_id, text in texts:
        for raw in dict.fromkeys(_RAW_ID_RE.findall(text or "")):
            rep.add("raw_id", node_id, f"raw id '{raw}' in authored text of {node_id}")


def _note_entries(repo: Repo, rep: IntegrityReport) -> int:
    entries = [
        f for f in repo.list_state_facts() if is_scene_entry_cause(f.caused_by_event_id)
    ]
    for f in entries:
        rep.add(
            "implicit_entry",
            f.entity_id,
            f"{f.entity_id} relocated to '{f.value}' at order {f.valid_from_order} by {f.caused_by_event_id}",
            "info",
        )
    return len(entries)


def build_integrity_report(repo: Repo) -> IntegrityReport:
    """Run every integrity check over the current graph in O(V + E + shots·cast)."""
    rep = IntegrityReport(project_id=repo.project_id)
    events = sorted(repo.list_events(), key=lambda e: (e.story_order, e.id))
    facts = repo.list_state_facts()
    idx = _Facts(facts)
    _check_events(rep, events)
    _check_holders(rep, facts)
    _check_lifecycles(repo, rep, idx)
    _check_clip_chain(repo, rep, idx)
    _check_cast_location(repo, rep, idx)
    _check_orphans(repo, rep, events)
    _check_raw_ids(repo, rep, events)
    rep.stats = {
        "scenes": len(repo.list_scenes()),
        "shots": len(repo.list_shots()),
        "events": len(events),
        "state_facts": len(facts),
        "scene_entry_facts": _note_entries(repo, rep),
    }
    return rep


def to_stage_report(rep: IntegrityReport) -> StageQaReport:
    """Stage-QA view of the integrity report (informational: it never blocks)."""
    errors = sum(1 for f in rep.findings if f.severity == "error")
    issues = [
        StageQaIssue(
            code=f"GI_{f.kind.upper()}",
            severity="error" if f.severity == "error" else "warn",
            node_id=f.node_id,
            dimension="graph_integrity",
            message=f.message,
        )
        for f in rep.findings
        if f.severity != "info"
    ]
    return StageQaReport(
        id=f"sqa_{STAGE}_{uuid.uuid4().hex[:8]}",
        created_by=Role.CRITIC,
        status=Status.APPROVED if not errors else Status.NEEDS_REVISION,
        stage=STAGE,
        passed=not errors,
        score=max(0.0, round(1.0 - 0.02 * len(issues), 2)),
        issues=issues,
        summary=f"Graph integrity: {rep.counts} stats={rep.stats}",
    )


def record_integrity_report(repo: Repo) -> StageQaReport:
    """Build, persist (stage QA report) and log the integrity report."""
    rep = build_integrity_report(repo)
    report = to_stage_report(rep)
    repo.store.set("stage_qa_reports", report.id, report.model_dump(mode="json"))
    _log.info(
        "graph_integrity_report",
        extra={
            "who": "storygraph.graph_integrity",
            "where": f"project:{repo.project_id}",
            "what": report.summary,
            "when": datetime.now(UTC).isoformat(),
            "why": "surface graph defects after S5 before validation/render",
            "how": "deterministic O(V+E) checks over events, facts, shots and text",
        },
    )
    return report
