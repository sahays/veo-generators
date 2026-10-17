"""Deterministic 10-Stage Story-to-Video Graph Pipeline Controller (`S0_INGEST` .. `S10_ASSEMBLE`)."""

from __future__ import annotations

import hashlib
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from enum import StrEnum

from ..adapters.base import ImageGenerator, TTSProvider, VideoGenerator, VLMProvider
from ..adapters.gemini_image import GeminiImageGenerator
from ..adapters.gemini_video import GeminiVideoGenerator
from ..adapters.mock import (
    MockImageGenerator,
    MockLLMClient,
    MockTTSProvider,
    MockVideoGenerator,
    MockVLMProvider,
)
from ..adapters.vlm import CloudTTSProvider, GeminiVLMProvider
from ..agents.critic import evaluate_clip_qa
from ..agents.design_studio import run_visual_design_studio
from ..agents.roles import (
    run_director_for_scene,
    run_music_director,
    run_screenwriter_for_scene,
    run_script_supervisor,
    run_story_architect,
)
from ..assemble import assemble
from ..budget import select_references
from ..compile import Package, compile_shot
from ..config import Config
from ..errors import BudgetExceeded, GateBlocked, ValidationFailed
from ..repo import Repo
from ..schema import GenerationRun, Role, Shot, StageRun, Status
from ..state import rebuild_state_facts

from ..tools import write_tools as wt
from ..tools.registry import ToolContext
from ..validate import validate_all
from ..views import shot_view
from .gates import approve_gate, ensure_gate, require_gate


class Stage(StrEnum):
    S0_INGEST = "S0_INGEST"
    S1_EXTRACT = "S1_EXTRACT"
    S2_SCREENPLAY = "S2_SCREENPLAY"
    S3_DESIGN = "S3_DESIGN"
    S4_SHOTS = "S4_SHOTS"
    S5_MUSIC = "S5_MUSIC"
    S6_VALIDATE = "S6_VALIDATE"
    S7_COMPILE = "S7_COMPILE"
    S8_RENDER = "S8_RENDER"
    S9_QA = "S9_QA"
    S10_ASSEMBLE = "S10_ASSEMBLE"


STAGE_ORDER: list[Stage] = [
    Stage.S0_INGEST,
    Stage.S1_EXTRACT,
    Stage.S2_SCREENPLAY,
    Stage.S3_DESIGN,
    Stage.S4_SHOTS,
    Stage.S5_MUSIC,
    Stage.S6_VALIDATE,
    Stage.S7_COMPILE,
    Stage.S8_RENDER,
    Stage.S9_QA,
    Stage.S10_ASSEMBLE,
]


class Pipeline:
    """Deterministic state-machine controller for the Story-to-Video Graph pipeline."""

    def __init__(
        self,
        repo: Repo,
        cfg: Config | None = None,
        image_gen: ImageGenerator | None = None,
        video_gen: VideoGenerator | None = None,
        vlm: VLMProvider | None = None,
        tts: TTSProvider | None = None,
        mock_llm: MockLLMClient | None = None,
    ) -> None:
        self.repo = repo
        self.cfg = cfg or Config.load()
        self.image_gen: ImageGenerator = image_gen or (
            MockImageGenerator()
            if self.cfg.image.provider == "mock"
            else GeminiImageGenerator(model=self.cfg.image.model)
        )
        self.video_gen: VideoGenerator = video_gen or (
            MockVideoGenerator(caps=self.cfg.video)
            if self.cfg.video.provider == "mock"
            else GeminiVideoGenerator(caps=self.cfg.video)
        )
        self.vlm: VLMProvider = vlm or (
            MockVLMProvider()
            if self.cfg.image.provider == "mock"
            else GeminiVLMProvider(model=self.cfg.models.critic_vlm)
        )
        self.tts: TTSProvider = tts or (
            MockTTSProvider()
            if self.cfg.image.provider == "mock"
            else CloudTTSProvider()
        )
        self.mock_llm = mock_llm
        self.compiled_packages: dict[str, Package] = {}

    def _compute_stage_input_hash(self, stage: Stage) -> str:
        payload: dict = {"stage": str(stage), "source": self.repo.get_source_text()}
        if stage in (Stage.S2_SCREENPLAY, Stage.S3_DESIGN):
            payload["entities"] = [(e.id, e.version) for e in self.repo.list_entities()]
            payload["events"] = [(e.id, e.version) for e in self.repo.list_events()]
        elif stage in (Stage.S4_SHOTS, Stage.S5_MUSIC):
            payload["scenes"] = [(s.id, s.version) for s in self.repo.list_scenes()]
            payload["appearances"] = [
                (a.id, a.version, str(a.status)) for a in self.repo.list_appearances()
            ]
        elif stage in (
            Stage.S6_VALIDATE,
            Stage.S7_COMPILE,
            Stage.S8_RENDER,
            Stage.S9_QA,
            Stage.S10_ASSEMBLE,
        ):
            payload["shots"] = [
                (s.id, s.version, s.stale) for s in self.repo.list_shots()
            ]
        raw = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _check_budget_caps(self, new_tokens: int, new_cost_usd: float) -> None:
        if new_tokens > self.cfg.caps.stage_token_cap:
            raise BudgetExceeded(
                f"Stage token usage ({new_tokens}) exceeds stage_token_cap ({self.cfg.caps.stage_token_cap})"
            )
        total_cost = (
            sum(sr.cost_usd for sr in self.repo.list_stage_runs()) + new_cost_usd
        )
        if total_cost > self.cfg.caps.project_cost_cap_usd:
            raise BudgetExceeded(
                f"Project cumulative cost (${total_cost:.2f}) exceeds project_cost_cap_usd (${self.cfg.caps.project_cost_cap_usd:.2f})"
            )

    def _record_stage(
        self,
        stage: Stage,
        input_hash: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_usd: float = 0.0,
        error: str | None = None,
    ) -> StageRun:
        if error is None:
            self._check_budget_caps(tokens_in + tokens_out, cost_usd)
        sr = StageRun(
            id=f"sr_{stage}_{uuid.uuid4().hex[:8]}",
            created_by=Role.PIPELINE,
            status=Status.APPROVED if error is None else Status.FAILED,
            stage=str(stage),
            input_hash=input_hash,
            completed=error is None,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            error=error,
        )
        saved = self.repo.record_stage_run(sr)
        meta = self.repo.get_project_meta()
        if meta:
            self.repo.put_project_meta(
                meta.model_copy(
                    update={
                        "current_stage": str(stage),
                        "status": "completed"
                        if stage == Stage.S10_ASSEMBLE and error is None
                        else ("failed" if error else "running"),
                        "error_message": error,
                    }
                )
            )
        return saved

    def ingest_story(self, story_text: str) -> StageRun:
        self.repo.put_source_text(story_text)
        ihash = self._compute_stage_input_hash(Stage.S0_INGEST)
        return self._record_stage(Stage.S0_INGEST, ihash)

    def run_stage(self, stage: Stage | str, force: bool = False) -> StageRun:
        st = Stage(stage)
        ihash = self._compute_stage_input_hash(st)
        try:
            return self._execute_stage(st, ihash, force=force)
        except GateBlocked:
            raise
        except Exception as exc:
            self._record_stage(st, ihash, error=str(exc))
            raise

    def _execute_stage(self, st: Stage, ihash: str, force: bool = False) -> StageRun:
        # Idempotent skip if already completed with identical input_hash and no stale shots
        if not force and st not in (Stage.S8_RENDER, Stage.S9_QA):
            prev_runs = self.repo.list_stage_runs(stage=str(st))
            if any(r.completed and r.input_hash == ihash for r in prev_runs):
                return prev_runs[-1]

        meta = self.repo.get_project_meta()
        aspect_ratio = meta.orientation if meta else "16:9"
        language = meta.language if meta else "en-IN"
        auto_approve = meta.auto_approve_gates if meta else False

        if st == Stage.S0_INGEST:
            text = self.repo.get_source_text() or (meta.base_concept if meta else "")
            return self.ingest_story(text)

        if st == Stage.S1_EXTRACT:
            story_text = self.repo.get_source_text() or (
                meta.base_concept if meta else ""
            )
            sa_ctx = ToolContext(
                repo=self.repo, role=Role.STORY_ARCHITECT, cfg=self.cfg
            )
            ss_ctx = ToolContext(
                repo=self.repo, role=Role.SCRIPT_SUPERVISOR, cfg=self.cfg
            )
            r1 = run_story_architect(
                sa_ctx, story_text, aspect_ratio=aspect_ratio, mock_llm=self.mock_llm
            )
            r2 = run_script_supervisor(ss_ctx, story_text, mock_llm=self.mock_llm)
            ensure_gate(self.repo, "G1", str(Stage.S1_EXTRACT))
            if auto_approve:
                approve_gate(self.repo, "G1", reviewer="auto_approve")
            tin = r1.tokens_in + r2.tokens_in
            tout = r1.tokens_out + r2.tokens_out
            return self._record_stage(
                st, ihash, tokens_in=tin, tokens_out=tout, cost_usd=0.01
            )

        if st == Stage.S2_SCREENPLAY:
            require_gate(self.repo, "G1")
            scenes = self.repo.list_scenes()
            sw_ctx = ToolContext(repo=self.repo, role=Role.SCREENWRITER, cfg=self.cfg)
            tin, tout = 0, 0
            with ThreadPoolExecutor(max_workers=max(1, len(scenes))) as pool:
                futs = [
                    pool.submit(
                        run_screenwriter_for_scene,
                        sw_ctx,
                        sc.id,
                        language,
                        self.mock_llm,
                    )
                    for sc in scenes
                ]
                for f in futs:
                    res = f.result()
                    tin += res.tokens_in
                    tout += res.tokens_out
            return self._record_stage(
                st, ihash, tokens_in=tin, tokens_out=tout, cost_usd=0.01
            )

        if st == Stage.S3_DESIGN:
            require_gate(self.repo, "G1")
            _, tin, tout = run_visual_design_studio(
                self.repo,
                self.cfg,
                image_gen=self.image_gen,
                vlm=self.vlm,
                mock_llm=self.mock_llm,
                force_regenerate=force,
            )
            ensure_gate(self.repo, "G2", str(Stage.S3_DESIGN))
            if auto_approve:
                approve_gate(self.repo, "G2", reviewer="auto_approve")
            return self._record_stage(
                st, ihash, tokens_in=tin, tokens_out=tout, cost_usd=0.08
            )

        if st == Stage.S4_SHOTS:
            require_gate(self.repo, "G2")
            scenes = self.repo.list_scenes()
            dir_ctx = ToolContext(repo=self.repo, role=Role.DIRECTOR, cfg=self.cfg)
            tin, tout = 0, 0
            with ThreadPoolExecutor(max_workers=max(1, len(scenes))) as pool:
                futs = [
                    pool.submit(run_director_for_scene, dir_ctx, sc.id, self.mock_llm)
                    for sc in scenes
                ]
                for f in futs:
                    res = f.result()
                    tin += res.tokens_in
                    tout += res.tokens_out
            return self._record_stage(
                st, ihash, tokens_in=tin, tokens_out=tout, cost_usd=0.02
            )

        if st == Stage.S5_MUSIC:
            require_gate(self.repo, "G2")
            md_ctx = ToolContext(repo=self.repo, role=Role.MUSIC_DIRECTOR, cfg=self.cfg)
            res = run_music_director(md_ctx, mock_llm=self.mock_llm)
            ensure_gate(self.repo, "G3", str(Stage.S5_MUSIC))
            if auto_approve:
                approve_gate(self.repo, "G3", reviewer="auto_approve")
            return self._record_stage(
                st,
                ihash,
                tokens_in=res.tokens_in,
                tokens_out=res.tokens_out,
                cost_usd=0.01,
            )

        if st == Stage.S6_VALIDATE:
            require_gate(self.repo, "G3")
            rebuild_state_facts(self.repo)
            issues = validate_all(self.repo, self.cfg)
            errors = [i for i in issues if i.severity == "error"]
            if errors:
                raise ValidationFailed(errors)
            return self._record_stage(st, ihash)

        if st == Stage.S7_COMPILE:
            require_gate(self.repo, "G3")
            for shot in self.repo.list_shots():
                sv = shot_view(self.repo, shot.id)
                plan = select_references(
                    sv, self.cfg, caps=self.video_gen.caps, repo=self.repo
                )
                pkg = compile_shot(
                    sv,
                    plan,
                    self.cfg,
                    caps=self.video_gen.caps,
                    project_id=self.repo.project_id,
                    attempt=1,
                )
                self.compiled_packages[shot.id] = pkg
            return self._record_stage(st, ihash)

        if st == Stage.S8_RENDER:
            require_gate(self.repo, "G3")
            self._render_and_qa_shots()
            return self._record_stage(st, ihash, cost_usd=0.25)

        if st == Stage.S9_QA:
            require_gate(self.repo, "G3")
            # Ensure every shot has an approved QA report or run QA
            for shot in self.repo.list_shots():
                runs = self.repo.list_generation_runs(shot_id=shot.id)
                if runs and runs[-1].qa_scores is None:
                    evaluate_clip_qa(self.repo, self.cfg, self.vlm, shot, runs[-1])
            return self._record_stage(
                st, ihash, tokens_in=200, tokens_out=100, cost_usd=0.02
            )

        if st == Stage.S10_ASSEMBLE:
            require_gate(self.repo, "G3")
            assemble(self.repo)
            return self._record_stage(st, ihash)

        raise ValueError(f"Unsupported stage: {st}")

    def _render_single_shot_with_qa(self, shot: Shot, max_retries: int) -> None:
        existing_runs = self.repo.list_generation_runs(shot_id=shot.id)
        if (
            not shot.stale
            and existing_runs
            and (
                existing_runs[-1].status == Status.APPROVED
                or (
                    self.cfg.video.provider != "mock"
                    and len(existing_runs) >= max_retries
                    and bool(existing_runs[-1].output_video_uri)
                )
            )
        ):
            return

        start_attempt = len(existing_runs) + 1
        passed = False

        for offset in range(max_retries):
            attempt = start_attempt + offset
            sv = shot_view(self.repo, shot.id)
            plan = select_references(
                sv, self.cfg, caps=self.video_gen.caps, repo=self.repo
            )
            pkg = compile_shot(
                sv,
                plan,
                self.cfg,
                caps=self.video_gen.caps,
                project_id=self.repo.project_id,
                attempt=attempt,
            )
            self.compiled_packages[shot.id] = pkg

            clip_bytes = self.video_gen.generate(pkg)
            clip_uri = self.repo.blobs.put_bytes(
                f"clips/{shot.id}_att{attempt}_{pkg.package_hash[:8]}.mp4",
                clip_bytes,
                content_type="video/mp4",
            )
            signed_clip = (
                self.repo.blobs.sign_url(clip_uri)
                if hasattr(self.repo.blobs, "sign_url")
                else clip_uri
            )
            run_node = GenerationRun(
                id=f"run_{shot.id}_att{attempt}_{uuid.uuid4().hex[:6]}",
                created_by=Role.PIPELINE,
                status=Status.RENDERED,
                shot_id=shot.id,
                attempt=attempt,
                provider=self.cfg.video.provider,
                model=self.cfg.video.model,
                compiled_prompt=pkg.compiled_prompt,
                negative_prompt=pkg.negative_prompt,
                reference_asset_ids=pkg.reference_asset_ids,
                first_frame_asset_id=pkg.first_frame_asset_id,
                seed=pkg.seed,
                package_hash=pkg.package_hash,
                output_video_uri=clip_uri,
                output_video_signed_url=signed_clip,
            )
            self.repo.add_generation_run(run_node)

            qa_report = evaluate_clip_qa(self.repo, self.cfg, self.vlm, shot, run_node)
            if qa_report.passed:
                passed = True
                if shot.stale:
                    self.repo.put_shot(
                        shot.model_copy(update={"stale": False, "stale_reason": None})
                    )
                break

        if not passed:
            critic_ctx = ToolContext(repo=self.repo, role=Role.CRITIC, cfg=self.cfg)
            wt.create_change_request(
                critic_ctx,
                to_role=Role.DIRECTOR,
                target_node_id=shot.id,
                reason=f"Shot '{shot.id}' failed QA after {max_retries} attempt(s); suggested fix: resplit_shot",
                proposed_patch={"action": "resplit_shot"},
            )

    def _render_and_qa_shots(self) -> None:
        """Render dirty/unrendered shots in story_order (propagating last_frame within each scene)."""
        shots = sorted(
            self.repo.list_shots(),
            key=lambda s: (s.story_order, s.scene_id, s.index_in_scene),
        )
        max_retries = max(1, self.cfg.caps.shot_max_retries)

        if self.cfg.video.provider == "mock" or len(shots) <= 1:
            for shot in shots:
                self._render_single_shot_with_qa(shot, max_retries)
            return

        # Group shots by scene_id: scenes run in parallel while shots within each scene run sequentially
        scene_groups: dict[str, list[Shot]] = {}
        for shot in shots:
            scene_groups.setdefault(shot.scene_id, []).append(shot)

        def _run_scene_chain(scene_shots: list[Shot]) -> None:
            for sh in scene_shots:
                self._render_single_shot_with_qa(sh, max_retries)

        with ThreadPoolExecutor(max_workers=min(4, len(scene_groups))) as pool:
            futs = [pool.submit(_run_scene_chain, grp) for grp in scene_groups.values()]
            for fut in futs:
                fut.result()

    def run_until_gate_or_done(
        self,
        story_text: str | None = None,
        auto_approve_gates: bool | None = None,
    ) -> list[StageRun]:
        """Run the pipeline forward from the current state until blocked by an unapproved gate or finished."""
        meta = self.repo.get_project_meta()
        if auto_approve_gates is not None and meta is not None:
            meta = self.repo.put_project_meta(
                meta.model_copy(update={"auto_approve_gates": auto_approve_gates})
            )

        if story_text is not None and not self.repo.get_source_text():
            self.ingest_story(story_text)

        executed: list[StageRun] = []
        for stage in STAGE_ORDER[1:]:  # S1_EXTRACT .. S10_ASSEMBLE
            sr = self.run_stage(stage)
            executed.append(sr)
            if stage == Stage.S1_EXTRACT:
                require_gate(self.repo, "G1")
            elif stage == Stage.S3_DESIGN:
                require_gate(self.repo, "G2")
            elif stage == Stage.S5_MUSIC:
                require_gate(self.repo, "G3")
        return executed
