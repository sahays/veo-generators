"""Typed Repository (`Repo`) wrapping GraphStore and BlobStore with versioning and staleness propagation."""

from __future__ import annotations

import re
from typing import TypeVar

from .errors import AlreadyExists
from .schema import (
    Appearance,
    Asset,
    AuditEntry,
    ChangeRequest,
    DialogueLine,
    Entity,
    EntityType,
    Event,
    Gate,
    GenerationRun,
    MusicCue,
    NodeBase,
    ProjectMeta,
    QAReport,
    Scene,
    Shot,
    StageRun,
    StateFact,
    Status,
    StyleGuide,
)
from .store.base import BlobStore, Filter, GraphStore
from .store.codec import decode, encode

T = TypeVar("T", bound=NodeBase)
_VERSION_SUFFIX_RE = re.compile(r"^(?P<base>.+?)_v(?P<ver>\d+)$")


def _strip_version_suffix(node_id: str) -> str:
    m = _VERSION_SUFFIX_RE.match(node_id)
    return m.group("base") if m else node_id


class Repo:
    """Typed domain repository enforcing immutability, versioning, and staleness propagation."""

    def __init__(self, store: GraphStore, blobs: BlobStore) -> None:
        self.store = store
        self.blobs = blobs

    @property
    def project_id(self) -> str:
        return self.store.project_id

    # ── Project Meta & Source Text ────────────────────────────────────────────

    def put_project_meta(self, meta: ProjectMeta) -> ProjectMeta:
        self.store.set("meta", "project", meta.model_dump(mode="json"))
        return meta

    def get_project_meta(self) -> ProjectMeta | None:
        raw = self.store.get("meta", "project")
        return ProjectMeta.model_validate(raw) if raw else None

    def put_source_text(self, text: str) -> None:
        self.store.set("meta", "source", {"text": text})

    def get_source_text(self) -> str:
        raw = self.store.get("meta", "source")
        return str(raw.get("text", "")) if raw else ""

    # ── StyleGuide ────────────────────────────────────────────────────────────

    def get_style_guide(self) -> StyleGuide | None:
        raw = self.store.get("meta", "style_guide")
        return decode(raw, StyleGuide) if raw else None

    def put_style_guide(self, sg: StyleGuide) -> StyleGuide:
        existing = self.get_style_guide()
        next_ver = (existing.version + 1) if existing else 1
        updated = sg.model_copy(update={"id": "style_guide", "version": next_ver})
        self.store.set("meta", "style_guide", encode(updated))
        return updated

    # ── Entities ──────────────────────────────────────────────────────────────

    def get_entity(self, entity_id: str) -> Entity | None:
        raw = self.store.get("entities", entity_id)
        return decode(raw, Entity) if raw else None

    def list_entities(self, entity_type: EntityType | None = None) -> list[Entity]:
        filters: list[Filter] = (
            [("entity_type", "==", str(entity_type))] if entity_type else []
        )
        rows = self.store.query("entities", filters=filters, order_by="id")
        return [decode(r, Entity) for r in rows]

    def put_entity(self, ent: Entity) -> Entity:
        existing = self.get_entity(ent.id)
        next_ver = (existing.version + 1) if existing else 1
        updated = ent.model_copy(update={"version": next_ver})
        self.store.set("entities", updated.id, encode(updated))
        return updated

    # ── Events & StateFacts ───────────────────────────────────────────────────

    def get_event(self, event_id: str) -> Event | None:
        raw = self.store.get("events", event_id)
        return decode(raw, Event) if raw else None

    def list_events(self, scene_id: str | None = None) -> list[Event]:
        filters: list[Filter] = [("scene_id", "==", scene_id)] if scene_id else []
        rows = self.store.query("events", filters=filters, order_by="story_order")
        return [decode(r, Event) for r in rows]

    def put_event(self, ev: Event) -> Event:
        existing = self.get_event(ev.id)
        next_ver = (existing.version + 1) if existing else 1
        updated = ev.model_copy(update={"version": next_ver})
        self.store.set("events", updated.id, encode(updated))
        return updated

    def list_state_facts(self, entity_id: str | None = None) -> list[StateFact]:
        filters: list[Filter] = [("entity_id", "==", entity_id)] if entity_id else []
        rows = self.store.query(
            "state_facts", filters=filters, order_by="valid_from_order"
        )
        return [decode(r, StateFact) for r in rows]

    def replace_all_state_facts(self, facts: list[StateFact]) -> None:
        existing = self.store.query("state_facts")
        with self.store.batch() as b:
            for old in existing:
                b.delete("state_facts", old["id"])
            for f in facts:
                b.set("state_facts", f.id, encode(f))

    # ── Appearances & Assets (Immutable Versioned Nodes) ──────────────────────

    def get_appearance(self, appearance_id: str) -> Appearance | None:
        raw = self.store.get("appearances", appearance_id)
        return decode(raw, Appearance) if raw else None

    def list_appearances(
        self, entity_id: str | None = None, active_only: bool = True
    ) -> list[Appearance]:
        filters: list[Filter] = [("entity_id", "==", entity_id)] if entity_id else []
        rows = self.store.query("appearances", filters=filters, order_by="version")
        apps = [decode(r, Appearance) for r in rows]
        if active_only:
            apps = [a for a in apps if a.status != Status.SUPERSEDED]
        return apps

    def add_appearance(self, app: Appearance) -> Appearance:
        """Mint a new versioned Appearance (`v1`, `v2`...) inside a transaction and mark referencing shots stale."""
        base_id = f"app_{app.entity_id}_{app.state_label}"
        superseded_ids: list[str] = []

        with self.store.transaction() as tx:
            existing_all = self.store.query(
                "appearances",
                filters=[
                    ("entity_id", "==", app.entity_id),
                    ("state_label", "==", app.state_label),
                ],
            )
            max_ver = max((int(d.get("version", 0)) for d in existing_all), default=0)
            new_ver = max_ver + 1
            new_id = f"{base_id}_v{new_ver}"

            prev_active = [
                d for d in existing_all if d.get("status") != str(Status.SUPERSEDED)
            ]
            supersedes_id = prev_active[-1]["id"] if prev_active else app.supersedes

            for prev in prev_active:
                prev_copy = dict(prev)
                prev_copy["status"] = str(Status.SUPERSEDED)
                tx.set("appearances", prev["id"], prev_copy)
                superseded_ids.append(prev["id"])

            minted = app.model_copy(
                update={
                    "id": new_id,
                    "version": new_ver,
                    "supersedes": supersedes_id,
                }
            )
            tx.set("appearances", minted.id, encode(minted))

        for old_id in superseded_ids:
            self._propagate_staleness(
                old_id, f"Appearance {old_id} superseded by {minted.id}"
            )
        return minted

    def update_appearance_status(
        self,
        appearance_id: str,
        status: Status,
        asset_ids: list[str] | None = None,
    ) -> Appearance:
        app = self.get_appearance(appearance_id)
        if not app:
            raise ValueError(f"Appearance {appearance_id} not found")
        updates: dict = {"status": status}
        if asset_ids is not None:
            updates["asset_ids"] = asset_ids
        updated = app.model_copy(update=updates)
        self.store.set("appearances", updated.id, encode(updated))
        return updated

    def get_asset(self, asset_id: str) -> Asset | None:
        raw = self.store.get("assets", asset_id)
        return decode(raw, Asset) if raw else None

    def list_assets(self, kind: str | None = None) -> list[Asset]:
        filters: list[Filter] = [("kind", "==", kind)] if kind else []
        rows = self.store.query("assets", filters=filters, order_by="version")
        return [decode(r, Asset) for r in rows]

    def add_asset(self, asset: Asset) -> Asset:
        """Mint a new versioned Asset (`_v1`, `_v2`...) and propagate staleness if superseding."""
        base_id = _strip_version_suffix(asset.id)
        superseded_ids: list[str] = []

        with self.store.transaction() as tx:
            all_assets = self.store.query("assets")
            matching = [
                d
                for d in all_assets
                if _strip_version_suffix(str(d.get("id", ""))) == base_id
            ]
            max_ver = max((int(d.get("version", 0)) for d in matching), default=0)
            new_ver = max_ver + 1
            new_id = f"{base_id}_v{new_ver}"

            prev_active = [
                d for d in matching if d.get("status") != str(Status.SUPERSEDED)
            ]
            supersedes_id = prev_active[-1]["id"] if prev_active else asset.supersedes

            for prev in prev_active:
                prev_copy = dict(prev)
                prev_copy["status"] = str(Status.SUPERSEDED)
                tx.set("assets", prev["id"], prev_copy)
                superseded_ids.append(prev["id"])

            minted = asset.model_copy(
                update={
                    "id": new_id,
                    "version": new_ver,
                    "supersedes": supersedes_id,
                }
            )
            tx.set("assets", minted.id, encode(minted))

        for app_id in minted.appearance_ids:
            app_node = self.get_appearance(app_id)
            if app_node and minted.id not in app_node.asset_ids:
                new_asset_ids = [
                    aid for aid in app_node.asset_ids if aid not in superseded_ids
                ] + [minted.id]
                self.update_appearance_status(
                    app_node.id, app_node.status, asset_ids=new_asset_ids
                )
            for old_asset_id in superseded_ids:
                self._propagate_staleness(
                    app_id, f"Asset {old_asset_id} superseded by {minted.id}"
                )

        for old_id in superseded_ids:
            self._propagate_staleness(
                old_id, f"Asset {old_id} superseded by {minted.id}"
            )
        return minted

    def update_asset(
        self,
        asset_id: str,
        status: Status | None = None,
        qa_notes: str | None = None,
    ) -> Asset:
        asset = self.get_asset(asset_id)
        if not asset:
            raise ValueError(f"Asset {asset_id} not found")
        updates: dict = {}
        if status is not None:
            updates["status"] = status
        if qa_notes is not None:
            updates["qa_notes"] = qa_notes
        updated = asset.model_copy(update=updates)
        self.store.set("assets", updated.id, encode(updated))
        return updated

    # ── Scenes, DialogueLines, MusicCues, Shots ───────────────────────────────

    def get_scene(self, scene_id: str) -> Scene | None:
        raw = self.store.get("scenes", scene_id)
        return decode(raw, Scene) if raw else None

    def list_scenes(self) -> list[Scene]:
        rows = self.store.query("scenes", order_by="index")
        return [decode(r, Scene) for r in rows]

    def put_scene(self, scene: Scene) -> Scene:
        existing = self.get_scene(scene.id)
        next_ver = (existing.version + 1) if existing else 1
        updated = scene.model_copy(update={"version": next_ver})
        self.store.set("scenes", updated.id, encode(updated))
        return updated

    def get_dialogue(self, line_id: str) -> DialogueLine | None:
        raw = self.store.get("dialogue_lines", line_id)
        return decode(raw, DialogueLine) if raw else None

    def list_dialogue(
        self, scene_id: str | None = None, shot_id: str | None = None
    ) -> list[DialogueLine]:
        filters: list[Filter] = []
        if scene_id:
            filters.append(("scene_id", "==", scene_id))
        if shot_id:
            filters.append(("shot_id", "==", shot_id))
        rows = self.store.query(
            "dialogue_lines", filters=filters, order_by="order_in_scene"
        )
        return [decode(r, DialogueLine) for r in rows]

    def put_dialogue(self, line: DialogueLine) -> DialogueLine:
        existing = self.get_dialogue(line.id)
        next_ver = (existing.version + 1) if existing else 1
        updated = line.model_copy(update={"version": next_ver})
        self.store.set("dialogue_lines", updated.id, encode(updated))
        return updated

    def get_music_cue(self, cue_id: str) -> MusicCue | None:
        raw = self.store.get("music_cues", cue_id)
        return decode(raw, MusicCue) if raw else None

    def list_music_cues(self, scene_id: str | None = None) -> list[MusicCue]:
        filters: list[Filter] = [("scene_id", "==", scene_id)] if scene_id else []
        rows = self.store.query("music_cues", filters=filters, order_by="id")
        return [decode(r, MusicCue) for r in rows]

    def put_music_cue(self, cue: MusicCue) -> MusicCue:
        existing = self.get_music_cue(cue.id)
        next_ver = (existing.version + 1) if existing else 1
        updated = cue.model_copy(update={"version": next_ver})
        self.store.set("music_cues", updated.id, encode(updated))
        return updated

    def get_shot(self, shot_id: str) -> Shot | None:
        raw = self.store.get("shots", shot_id)
        return decode(raw, Shot) if raw else None

    def list_shots(
        self, scene_id: str | None = None, stale_only: bool = False
    ) -> list[Shot]:
        filters: list[Filter] = []
        if scene_id:
            filters.append(("scene_id", "==", scene_id))
        if stale_only:
            filters.append(("stale", "==", True))
        rows = self.store.query("shots", filters=filters, order_by="story_order")
        return [decode(r, Shot) for r in rows]

    def put_shot(self, shot: Shot) -> Shot:
        """Persist a Shot after deterministically resolving appearance_ids and denormalizing ref_ids."""
        from .state import appearance_for

        existing = self.get_shot(shot.id)
        next_ver = (existing.version + 1) if existing else 1

        loc_app_id = shot.location_appearance_id
        if not loc_app_id and shot.location_id:
            try:
                loc_app = appearance_for(self, shot.location_id, shot.story_order)
                loc_app_id = loc_app.id
            except Exception:
                loc_app_id = ""

        resolved_cast = []
        for c in shot.cast:
            app_id = c.appearance_id
            if not app_id and c.entity_id:
                try:
                    char_app = appearance_for(self, c.entity_id, shot.story_order)
                    app_id = char_app.id
                except Exception:
                    app_id = ""
            resolved_cast.append(c.model_copy(update={"appearance_id": app_id}))

        prop_app_ids = dict(shot.prop_appearance_ids)
        for pid in shot.prop_ids:
            if not prop_app_ids.get(pid):
                try:
                    p_app = appearance_for(self, pid, shot.story_order)
                    prop_app_ids[pid] = p_app.id
                except Exception:
                    pass

        ref_ids: list[str] = []
        if loc_app_id:
            ref_ids.append(loc_app_id)
        for c in resolved_cast:
            if c.appearance_id and c.appearance_id not in ref_ids:
                ref_ids.append(c.appearance_id)
        for pid, paid in prop_app_ids.items():
            if paid and paid not in ref_ids:
                ref_ids.append(paid)

        # Also include underlying asset_ids in ref_ids so asset superseding triggers array_contains
        for app_id in list(ref_ids):
            app_obj = self.get_appearance(app_id)
            if app_obj:
                for aid in app_obj.asset_ids:
                    if aid not in ref_ids:
                        ref_ids.append(aid)

        updated = shot.model_copy(
            update={
                "version": next_ver,
                "location_appearance_id": loc_app_id,
                "cast": resolved_cast,
                "prop_appearance_ids": prop_app_ids,
                "ref_ids": ref_ids,
            }
        )
        self.store.set("shots", updated.id, encode(updated))

        # Ensure parent scene links shot_id
        scene = self.get_scene(updated.scene_id)
        if scene and updated.id not in scene.shot_ids:
            self.put_scene(
                scene.model_copy(update={"shot_ids": [*scene.shot_ids, updated.id]})
            )
        return updated

    def mark_shots_stale_referencing(self, ref_id: str, reason: str) -> list[str]:
        return self._propagate_staleness(ref_id, reason)

    def _propagate_staleness(self, ref_id: str, reason: str) -> list[str]:
        rows = self.store.query(
            "shots", filters=[("ref_ids", "array_contains", ref_id)]
        )
        if not rows:
            return []
        affected: list[str] = []
        with self.store.batch() as b:
            for r in rows:
                shot = decode(r, Shot)
                updated = shot.model_copy(
                    update={
                        "stale": True,
                        "stale_reason": reason,
                        "version": shot.version + 1,
                    }
                )
                b.set("shots", updated.id, encode(updated))
                affected.append(updated.id)
        return affected

    # ── Append-Only GenerationRuns, ChangeRequests, Gates, StageRuns ──────────

    def add_generation_run(self, run: GenerationRun) -> GenerationRun:
        if self.store.get("generation_runs", run.id) is not None:
            raise AlreadyExists(f"GenerationRun {run.id} already exists (append-only)")
        self.store.set("generation_runs", run.id, encode(run))
        return run

    def update_generation_run_qa(
        self,
        run_id: str,
        qa_scores: QAReport,
        status: Status,
        extracted_last_frame_asset_id: str | None = None,
    ) -> GenerationRun:
        raw = self.store.get("generation_runs", run_id)
        if not raw:
            raise ValueError(f"GenerationRun {run_id} not found")
        run = decode(raw, GenerationRun)
        updates: dict = {
            "qa_scores": qa_scores,
            "status": status,
            "version": run.version + 1,
        }
        if extracted_last_frame_asset_id is not None:
            updates["extracted_last_frame_asset_id"] = extracted_last_frame_asset_id
        updated = run.model_copy(update=updates)
        self.store.set("generation_runs", updated.id, encode(updated))
        return updated

    def list_generation_runs(self, shot_id: str | None = None) -> list[GenerationRun]:
        filters: list[Filter] = [("shot_id", "==", shot_id)] if shot_id else []
        rows = self.store.query("generation_runs", filters=filters, order_by="attempt")
        return [decode(r, GenerationRun) for r in rows]

    def add_change_request(self, cr: ChangeRequest) -> ChangeRequest:
        if self.store.get("change_requests", cr.id) is not None:
            raise AlreadyExists(f"ChangeRequest {cr.id} already exists (append-only)")
        self.store.set("change_requests", cr.id, encode(cr))
        return cr

    def resolve_change_request(
        self, cr_id: str, resolution: str
    ) -> ChangeRequest | None:
        raw = self.store.get("change_requests", cr_id)
        if not raw:
            return None
        cr = decode(raw, ChangeRequest)
        updated = cr.model_copy(
            update={"resolution": resolution, "version": cr.version + 1}
        )
        self.store.set("change_requests", updated.id, encode(updated))
        return updated

    def list_change_requests(self, open_only: bool = True) -> list[ChangeRequest]:
        filters: list[Filter] = [("resolution", "==", "open")] if open_only else []
        rows = self.store.query("change_requests", filters=filters, order_by="id")
        return [decode(r, ChangeRequest) for r in rows]

    def get_gate(self, gate_id: str) -> Gate | None:
        raw = self.store.get("gates", gate_id)
        return decode(raw, Gate) if raw else None

    def list_gates(self) -> list[Gate]:
        rows = self.store.query("gates", order_by="gate_id")
        return [decode(r, Gate) for r in rows]

    def set_gate(self, gate: Gate) -> Gate:
        existing = self.get_gate(gate.gate_id)
        next_ver = (existing.version + 1) if existing else 1
        updated = gate.model_copy(update={"id": gate.gate_id, "version": next_ver})
        self.store.set("gates", gate.gate_id, encode(updated))
        return updated

    def record_stage_run(self, sr: StageRun) -> StageRun:
        if self.store.get("stage_runs", sr.id) is not None:
            raise AlreadyExists(f"StageRun {sr.id} already exists (append-only)")
        self.store.set("stage_runs", sr.id, encode(sr))
        return sr

    def list_stage_runs(self, stage: str | None = None) -> list[StageRun]:
        filters: list[Filter] = [("stage", "==", stage)] if stage else []
        rows = self.store.query("stage_runs", filters=filters, order_by="created_at")
        return [decode(r, StageRun) for r in rows]

    def list_audit_entries(self, limit: int = 200) -> list[AuditEntry]:
        rows = self.store.query("audit_log", order_by="-created_at", limit=limit)
        return [decode(r, AuditEntry) for r in rows]
