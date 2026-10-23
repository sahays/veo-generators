"""Lean production snapshot: everything the studio page renders on first paint, nothing more.

Pipeline: prefetch all collections concurrently (1 round trip each) -> answer every repo /
validator read from memory -> pick the active run per shot -> batch-sign only the URIs that
are actually returned (cached, bounded-parallel) -> serialize.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from storygraph.config import Config
from storygraph.repo import Repo
from storygraph.repo.prompt_versions import PromptVersionRepo
from storygraph.schema import Appearance, Asset, AuditEntry, GenerationRun, ProjectMeta
from storygraph.store.codec import decode
from storygraph.store.url_signing import sign_all
from storygraph.validate import validate_all

from . import sections, shaping
from .prefetch import Prefetched, PrefetchedStore, QuerySpec, prefetch

logger = logging.getLogger(__name__)

AUDIT_TAIL_LIMIT = 25
_FULL_COLLECTIONS: tuple[str, ...] = (
    "entities", "events", "state_facts", "appearances", "assets", "scenes",
    "dialogue_lines", "music_cues", "shots", "generation_runs", "gates",
    "stage_runs", "stage_qa_reports", "change_requests",
)  # fmt: skip
SNAPSHOT_SPECS: dict[str, QuerySpec] = {
    **{c: QuerySpec(c) for c in _FULL_COLLECTIONS},
    # Only active rows: the snapshot never needs prompt bodies of superseded versions.
    "prompt_versions": QuerySpec("prompt_versions", (("status", "==", "active"),)),
    "audit_tail": QuerySpec(
        "audit_log", order_by="-created_at", limit=AUDIT_TAIL_LIMIT
    ),
}
SNAPSHOT_DOCS: tuple[tuple[str, str], ...] = (
    ("meta", "project"),
    ("meta", "source"),
    ("meta", "style_guide"),
)
_HIDDEN_CR_STATUSES: frozenset[str] = frozenset({"superseded"})


@dataclass(frozen=True)
class _Graph:
    """Decoded nodes read once from the prefetched view."""

    view: Repo
    data: Prefetched
    meta: ProjectMeta
    assets_by_id: dict[str, Asset]
    appearances: list[Appearance]
    runs: list[GenerationRun]
    active_runs: dict[str, GenerationRun]


def _load_graph(repo: Repo) -> _Graph:
    data = prefetch(repo.store, SNAPSHOT_SPECS, SNAPSHOT_DOCS)
    view = Repo(
        store=PrefetchedStore(repo.store, data, SNAPSHOT_SPECS), blobs=repo.blobs
    )
    meta = view.get_project_meta()
    if meta is None:
        raise HTTPException(
            status_code=404, detail=f"Production {repo.project_id} not found"
        )
    runs = view.list_generation_runs()
    return _Graph(
        view=view,
        data=data,
        meta=meta,
        assets_by_id={a.id: a for a in view.list_assets()},
        appearances=view.list_appearances(active_only=False),
        runs=runs,
        active_runs=shaping.select_active_runs(runs),
    )


def _returned_assets(g: _Graph) -> tuple[list[Asset], set[str]]:
    """(run-only assets for `story_graph.assets`, every asset id embedded anywhere).

    Assets already embedded under an appearance are not repeated in `story_graph.assets`;
    the client indexes both lists to resolve a run's start/reference/end frames.
    """
    run_ids = shaping.run_asset_ids(g.active_runs.values())
    app_ids = shaping.appearance_asset_ids(g.appearances, g.assets_by_id)
    run_only = sorted(a for a in run_ids - app_ids if a in g.assets_by_id)
    return [g.assets_by_id[a] for a in run_only], run_ids | app_ids


def _sign_returned(g: _Graph, embedded_ids: set[str]) -> dict[str, str]:
    uris = [g.assets_by_id[a].uri for a in embedded_ids if a in g.assets_by_id]
    uris += [r.output_video_uri or "" for r in g.active_runs.values()]
    uris.append(g.meta.final_video_uri or "")
    return sign_all(g.view.blobs, uris)


def _appearances_out(g: _Graph, signed: dict[str, str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for app in g.appearances:
        apd = app.model_dump(mode="json")
        apd["assets"] = [
            shaping.asset_dict(g.assets_by_id[aid], signed)
            for aid in app.asset_ids
            if aid in g.assets_by_id
            and g.assets_by_id[aid].kind != shaping.COMPOSITE_KIND
        ]
        out.append(apd)
    return out


def _shots_out(g: _Graph) -> list[dict[str, Any]]:
    active_prompts = PromptVersionRepo(g.view.store).active_by_shot()
    out: list[dict[str, Any]] = []
    for sh in g.view.list_shots():
        shd = sh.model_dump(mode="json", exclude=set(shaping.SHOT_DETAIL_FIELDS))
        run = g.active_runs.get(sh.id)
        shd["latest_run_id"] = run.id if run else None
        pv = active_prompts.get(sh.id)
        shd["active_prompt_version"] = (
            {"id": pv.id, "version": pv.version, "author": pv.author} if pv else None
        )
        out.append(shd)
    return out


def _history_tail(g: _Graph) -> dict[str, Any]:
    crs = g.view.list_change_requests(open_only=False)
    tail = [decode(r, AuditEntry) for r in g.data.rows["audit_tail"]]
    return {
        "change_requests": [
            cr.model_dump(mode="json")
            for cr in crs
            if cr.status not in _HIDDEN_CR_STATUSES
        ],
        "audit_log": [ae.model_dump(mode="json") for ae in tail],
    }


def _story_graph(g: _Graph, cfg: Config, parts: dict[str, Any]) -> dict[str, Any]:
    v = g.view
    sg = v.get_style_guide()
    return {
        "style_guide": sections.serialize_style_guide(
            sg.model_dump(mode="json") if sg else None, g.meta
        ),
        "entities": sections.group_entities(v.list_entities()),
        "events": [e.model_dump(mode="json") for e in v.list_events()],
        "state_facts": [sf.model_dump(mode="json") for sf in v.list_state_facts()],
        "dialogue_lines": [d.model_dump(mode="json") for d in v.list_dialogue()],
        "music_cues": [m.model_dump(mode="json") for m in v.list_music_cues()],
        "gates": [gt.model_dump(mode="json") for gt in v.list_gates()],
        "stage_qa_reports": v.store.query("stage_qa_reports"),
        "validation_issues": [i.to_dict() for i in validate_all(v, cfg)],
        "generation_run_counts": shaping.count_runs_by_shot(g.runs),
        "generation_runs_total": len(g.runs),
        "asset_counts": shaping.count_assets_by_kind(g.assets_by_id.values()),
        **_history_tail(g),
        **parts,
    }


def format_graph_snapshot(repo: Repo, cfg: Config) -> dict[str, Any]:
    """Build the lean StoryGraph snapshot (contract: frontend `StoryGraphData`)."""
    t0 = time.perf_counter()
    g = _load_graph(repo)
    t_read = time.perf_counter()
    run_assets, embedded_ids = _returned_assets(g)
    signed = _sign_returned(g, embedded_ids)
    t_sign = time.perf_counter()
    snap = _assemble(g, cfg, signed, run_assets)
    _log_built(g, t0, t_read, t_sign, len(signed))
    return snap


def _assemble(
    g: _Graph, cfg: Config, signed: dict[str, str], run_assets: list[Asset]
) -> dict[str, Any]:
    stage_runs = g.view.list_stage_runs()
    scenes = g.view.list_scenes()
    shots_out = _shots_out(g)
    appearances_out = _appearances_out(g, signed)
    runs_out = {sid: shaping.run_summary(r, signed) for sid, r in g.active_runs.items()}
    parts = {
        "appearances": appearances_out,
        "assets": [shaping.asset_dict(a, signed) for a in run_assets],
        "scenes": [shaping.scene_summary(sc) for sc in scenes],
        "shots": shots_out,
        "generation_runs": list(runs_out.values()),
        "stage_runs": [sr.model_dump(mode="json") for sr in stage_runs],
    }
    shot_seconds = sum(float(s.get("duration_s", 0.0)) for s in shots_out)
    final_url = signed.get(g.meta.final_video_uri or "") or g.meta.final_video_url
    return {
        **sections.project_envelope(g.meta, g.view.get_source_text(), final_url),
        "scenes": sections.legacy_scenes(scenes, shots_out, appearances_out, runs_out),
        "total_usage": sections.usage_summary(
            cfg, stage_runs, list(g.assets_by_id.values()), len(g.runs), shot_seconds
        ),
        "story_graph": _story_graph(g, cfg, parts),
    }


def _log_built(
    g: _Graph, t0: float, t_read: float, t_sign: float, n_signed: int
) -> None:
    now = time.perf_counter()
    logger.info(
        "production_snapshot_built",
        extra={
            "who": "productions_service",
            "where": "services.snapshot.builder.format_graph_snapshot",
            "what": "production_snapshot_built",
            "when": datetime.now(UTC).isoformat(),
            "why": "studio page load / poll / post-mutation refresh",
            "how": "parallel prefetch + in-memory view + batched cached URL signing",
            "project_id": g.meta.id,
            "read_ms": round((t_read - t0) * 1000, 1),
            "sign_ms": round((t_sign - t_read) * 1000, 1),
            "shape_ms": round((now - t_sign) * 1000, 1),
            "runs_total": len(g.runs),
            "runs_returned": len(g.active_runs),
            "assets_total": len(g.assets_by_id),
            "urls_signed": n_signed,
        },
    )
