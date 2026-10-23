"""Typed Repository (`Repo`) wrapping GraphStore and BlobStore with versioning and staleness propagation."""

from __future__ import annotations

from typing import TypeVar

from ..errors import AlreadyExists
from ..schema import (
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
    StemSet,
    StyleGuide,
    VoiceoverRecord,
)
from ..store.base import BlobStore, Filter, GraphStore
from ..store.codec import decode, encode
from .change_requests import close_critic_change_requests
from .versioning import (
    mint_versioned_appearance,
    mint_versioned_asset,
    persist_shot_with_refs,
    propagate_staleness,
)

T = TypeVar("T", bound=NodeBase)


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
        return mint_versioned_appearance(self, app)

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
        return mint_versioned_asset(self, asset)

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
        return persist_shot_with_refs(self, shot)

    def delete_shot(self, shot_id: str) -> None:
        """Remove a Shot that no longer maps to any screenwriter clip."""
        self.store.delete("shots", shot_id)

    def mark_shots_stale_referencing(self, ref_id: str, reason: str) -> list[str]:
        return self._propagate_staleness(ref_id, reason)

    def _propagate_staleness(self, ref_id: str, reason: str) -> list[str]:
        return propagate_staleness(self, ref_id, reason)

    # ── Append-Only GenerationRuns, ChangeRequests, Gates, StageRuns ──────────

    def add_generation_run(self, run: GenerationRun) -> GenerationRun:
        if self.store.get("generation_runs", run.id) is not None:
            raise AlreadyExists(f"GenerationRun {run.id} already exists (append-only)")
        self.store.set("generation_runs", run.id, encode(run))
        close_critic_change_requests(self.store, run.shot_id, "rerendered")
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
        if status == Status.APPROVED:
            close_critic_change_requests(self.store, run.shot_id, "approved_run")
        return updated

    def list_generation_runs(self, shot_id: str | None = None) -> list[GenerationRun]:
        filters: list[Filter] = [("shot_id", "==", shot_id)] if shot_id else []
        rows = self.store.query("generation_runs", filters=filters, order_by="attempt")
        return [decode(r, GenerationRun) for r in rows]

    def _update_run(self, run_id: str, updates: dict[str, object]) -> GenerationRun:
        raw = self.store.get("generation_runs", run_id)
        if not raw:
            raise ValueError(f"GenerationRun {run_id} not found")
        run = decode(raw, GenerationRun)
        updated = run.model_copy(update={**updates, "version": run.version + 1})
        self.store.set("generation_runs", updated.id, encode(updated))
        return updated

    def record_voiceover(self, run_id: str, record: VoiceoverRecord) -> GenerationRun:
        """Attach a voiced clip to a run; `output_video_uri` (Omni original) is untouched."""
        return self._update_run(
            run_id, {"voiced_video_uri": record.voiced_video_uri, "voiceover": record}
        )

    def record_stems(self, run_id: str, stems: StemSet) -> GenerationRun:
        """Attach dialogue/SFX stems to a run (append-only; remix without re-render)."""
        return self._update_run(run_id, {"stems": stems})

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
