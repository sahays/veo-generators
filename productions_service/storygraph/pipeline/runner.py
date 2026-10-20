"""Deterministic 10-Stage Story-to-Video Graph Pipeline Controller (`S0_INGEST` .. `S10_ASSEMBLE`)."""

from __future__ import annotations

import hashlib
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

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
from ..agents.design_studio import run_visual_design_studio
from ..agents.roles import (
    run_director_for_scene,
    run_music_director,
    run_screenwriter_for_scene,
    run_script_supervisor,
    run_story_architect,
)
from ..agents.stage_qa import run_stage_qa_and_remediate, stages_to_redo_for_issues
from ..compile import Package
from ..config import Config
from ..errors import BudgetExceeded, GateBlocked, ShotsNotApproved, ValidationFailed
from ..repo import Repo
from ..schema import Role, StageRun, Status
from ..state import rebuild_state_facts
from ..tools.registry import ToolContext
from ..validate import validate_all
from .assemble_stage import project_status_after_stage, run_assemble_stage
from .gates import GATE_FOR_STAGE, approve_gate, ensure_gate, require_gate
from .lint_stage import MAX_LLM_ROUNDS, LintStageDeps, compile_and_lint
from .render_stage import (
    evaluate_missing_qa,
    render_and_qa_shots,
)
from .stages import AUTHORING_STAGES, STAGE_ORDER, Stage

__all__ = ["STAGE_ORDER", "Pipeline", "Stage"]


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
        is_mock_img = self.cfg.image.provider == "mock"
        self.image_gen: ImageGenerator = image_gen or (
            MockImageGenerator()
            if is_mock_img
            else GeminiImageGenerator(model=self.cfg.image.model)
        )
        self.video_gen: VideoGenerator = video_gen or (
            MockVideoGenerator(caps=self.cfg.video)
            if self.cfg.video.provider == "mock"
            else GeminiVideoGenerator(caps=self.cfg.video)
        )
        self.vlm: VLMProvider = vlm or (
            MockVLMProvider()
            if is_mock_img
            else GeminiVLMProvider(model=self.cfg.models.critic_vlm)
        )
        self.tts: TTSProvider = tts or (
            MockTTSProvider() if is_mock_img else CloudTTSProvider()
        )
        self.mock_llm = mock_llm
        self.compiled_packages: dict[str, Package] = {}
        self._auto_approve_override: bool | None = None
        self._allow_partial_assembly = False

    def _compute_stage_input_hash(self, stage: Stage) -> str:
        payload: dict[str, Any] = {
            "stage": str(stage),
            "source": self.repo.get_source_text(),
        }
        if stage in (Stage.S2_SCREENPLAY, Stage.S3_DESIGN):
            payload["entities"] = [(e.id, e.version) for e in self.repo.list_entities()]
            payload["events"] = [(e.id, e.version) for e in self.repo.list_events()]
        elif stage in (Stage.S4_SHOTS, Stage.S5_MUSIC):
            payload["scenes"] = [(s.id, s.version) for s in self.repo.list_scenes()]
            payload["appearances"] = [
                (a.id, a.version, str(a.status)) for a in self.repo.list_appearances()
            ]
        elif stage not in (Stage.S0_INGEST, Stage.S1_EXTRACT):
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

    def _update_project_stage_status(
        self, stage: Stage, error: str | None, needs_review: bool = False
    ) -> None:
        meta = self.repo.get_project_meta()
        if not meta:
            return
        is_s10 = stage == Stage.S10_ASSEMBLE
        status_val = project_status_after_stage(
            is_s10, meta.status, error, needs_review
        )
        # A successful S10 keeps assemble()'s note (e.g. skipped shots in partial mode).
        note = meta.error_message if is_s10 and error is None else error
        self.repo.put_project_meta(
            meta.model_copy(
                update={
                    "current_stage": str(stage),
                    "status": status_val,
                    "error_message": note,
                }
            )
        )

    def _record_stage(
        self,
        stage: Stage,
        input_hash: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_usd: float = 0.0,
        error: str | None = None,
        needs_review: bool = False,
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
        self._update_project_stage_status(stage, error, needs_review)
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
            review = isinstance(exc, ShotsNotApproved)
            self._record_stage(st, ihash, error=str(exc), needs_review=review)
            raise

    def assemble_approved_only(self) -> StageRun:
        """Manually stitch only APPROVED shots (skipping blocking ones) as an S10 run."""
        self._allow_partial_assembly = True
        try:
            return self.run_stage(Stage.S10_ASSEMBLE, force=True)
        finally:
            self._allow_partial_assembly = False

    def _execute_stage(self, st: Stage, ihash: str, force: bool = False) -> StageRun:
        if not force and st not in (Stage.S8_RENDER, Stage.S9_QA):
            prev_runs = self.repo.list_stage_runs(stage=str(st))
            if any(r.completed and r.input_hash == ihash for r in prev_runs):
                return prev_runs[-1]
        if st in AUTHORING_STAGES:
            return self._execute_authoring_stage(st, ihash, force=force)
        return self._execute_production_stage(st, ihash)

    def _execute_authoring_stage(
        self, st: Stage, ihash: str, force: bool = False
    ) -> StageRun:
        meta = self.repo.get_project_meta()
        aspect_ratio = meta.orientation if meta else "16:9"
        language = meta.language if meta else "en-IN"
        auto_approve = (
            self._auto_approve_override
            if self._auto_approve_override is not None
            else (meta.auto_approve_gates if meta else True)
        )
        story_text = self.repo.get_source_text() or (meta.base_concept if meta else "")

        if st == Stage.S0_INGEST:
            return self.ingest_story(story_text)
        if st == Stage.S1_EXTRACT:
            return self._run_s1_extract(
                st, ihash, story_text, aspect_ratio, auto_approve
            )
        if st == Stage.S2_SCREENPLAY:
            return self._run_s2_screenplay(st, ihash, language)
        if st == Stage.S3_DESIGN:
            return self._run_s3_design(st, ihash, auto_approve, force)
        if st == Stage.S4_SHOTS:
            return self._run_s4_shots(st, ihash)
        return self._run_s5_music(st, ihash, auto_approve)

    def _run_s1_extract(
        self,
        st: Stage,
        ihash: str,
        story_text: str,
        aspect_ratio: str,
        auto_approve: bool,
    ) -> StageRun:
        sa_ctx = ToolContext(repo=self.repo, role=Role.STORY_ARCHITECT, cfg=self.cfg)
        ss_ctx = ToolContext(repo=self.repo, role=Role.SCRIPT_SUPERVISOR, cfg=self.cfg)
        r1 = run_story_architect(
            sa_ctx, story_text, aspect_ratio=aspect_ratio, mock_llm=self.mock_llm
        )
        r2 = run_script_supervisor(ss_ctx, story_text, mock_llm=self.mock_llm)
        run_stage_qa_and_remediate(self.repo, self.cfg, str(st))
        ensure_gate(self.repo, "G1", str(Stage.S1_EXTRACT))
        if auto_approve:
            approve_gate(self.repo, "G1", reviewer="auto_approve")
        return self._record_stage(
            st,
            ihash,
            tokens_in=r1.tokens_in + r2.tokens_in,
            tokens_out=r1.tokens_out + r2.tokens_out,
            cost_usd=0.01,
        )

    def _run_s2_screenplay(self, st: Stage, ihash: str, language: str) -> StageRun:
        require_gate(self.repo, "G1")
        scenes = self.repo.list_scenes()
        sw_ctx = ToolContext(repo=self.repo, role=Role.SCREENWRITER, cfg=self.cfg)
        tin, tout = 0, 0
        with ThreadPoolExecutor(max_workers=max(1, len(scenes))) as pool:
            futs = [
                pool.submit(
                    run_screenwriter_for_scene, sw_ctx, sc.id, language, self.mock_llm
                )
                for sc in scenes
            ]
            for f in futs:
                res = f.result()
                tin += res.tokens_in
                tout += res.tokens_out
        run_stage_qa_and_remediate(self.repo, self.cfg, str(st))
        return self._record_stage(
            st, ihash, tokens_in=tin, tokens_out=tout, cost_usd=0.01
        )

    def _run_s3_design(
        self, st: Stage, ihash: str, auto_approve: bool, force: bool
    ) -> StageRun:
        require_gate(self.repo, "G1")
        _, tin, tout = run_visual_design_studio(
            self.repo,
            self.cfg,
            image_gen=self.image_gen,
            vlm=self.vlm,
            mock_llm=self.mock_llm,
            force_regenerate=force,
        )
        run_stage_qa_and_remediate(self.repo, self.cfg, str(st))
        ensure_gate(self.repo, "G2", str(Stage.S3_DESIGN))
        if auto_approve:
            approve_gate(self.repo, "G2", reviewer="auto_approve")
        return self._record_stage(
            st, ihash, tokens_in=tin, tokens_out=tout, cost_usd=0.08
        )

    def _run_s4_shots(self, st: Stage, ihash: str) -> StageRun:
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
        rebuild_state_facts(self.repo)
        run_stage_qa_and_remediate(self.repo, self.cfg, str(st))
        return self._record_stage(
            st, ihash, tokens_in=tin, tokens_out=tout, cost_usd=0.02
        )

    def _run_s5_music(self, st: Stage, ihash: str, auto_approve: bool) -> StageRun:
        require_gate(self.repo, "G2")
        md_ctx = ToolContext(repo=self.repo, role=Role.MUSIC_DIRECTOR, cfg=self.cfg)
        res = run_music_director(md_ctx, mock_llm=self.mock_llm)
        run_stage_qa_and_remediate(self.repo, self.cfg, str(st))
        ensure_gate(self.repo, "G3", str(Stage.S5_MUSIC))
        if auto_approve:
            approve_gate(self.repo, "G3", reviewer="auto_approve")
        return self._record_stage(
            st, ihash, tokens_in=res.tokens_in, tokens_out=res.tokens_out, cost_usd=0.01
        )

    def _review_and_redo_before_render(self, max_iterations: int = 3) -> None:
        """Review upstream artifacts and redo responsible agent stages up to `max_iterations` times."""
        for attempt in range(1, max_iterations + 1):
            report = run_stage_qa_and_remediate(
                self.repo, self.cfg, str(Stage.S5_MUSIC), max_iterations=max_iterations
            )
            rebuild_state_facts(self.repo)
            errors = [
                i for i in validate_all(self.repo, self.cfg) if i.severity == "error"
            ]
            open_crs = self.repo.list_change_requests(open_only=True)
            if report.passed and not errors and not open_crs:
                return
            if attempt == max_iterations:
                if errors:
                    raise ValidationFailed(errors)
                return
            for up_st in stages_to_redo_for_issues(report.issues, errors, open_crs):
                st_enum = Stage(up_st)
                self._execute_authoring_stage(
                    st_enum, self._compute_stage_input_hash(st_enum), force=True
                )
            for cr in open_crs:
                self.repo.resolve_change_request(cr.id, "accepted")

    def _compile_and_lint(self, max_llm_rounds: int = MAX_LLM_ROUNDS) -> None:
        """S7: compile + lint; deterministic remediation, then scene-scoped S2/S4 redo."""
        meta = self.repo.get_project_meta()
        deps = LintStageDeps(
            repo=self.repo,
            cfg=self.cfg,
            video_gen=self.video_gen,
            language=meta.language if meta else "en",
            mock_llm=self.mock_llm,
        )
        self.compiled_packages.update(compile_and_lint(deps, max_llm_rounds))

    def _execute_production_stage(self, st: Stage, ihash: str) -> StageRun:
        require_gate(self.repo, "G3")
        if st == Stage.S6_VALIDATE:
            self._review_and_redo_before_render(max_iterations=3)
            return self._record_stage(st, ihash)
        if st == Stage.S7_COMPILE:
            self._compile_and_lint()
            return self._record_stage(st, ihash)
        if st == Stage.S8_RENDER:
            render_and_qa_shots(
                self.repo, self.cfg, self.video_gen, self.vlm, self.compiled_packages
            )
            return self._record_stage(st, ihash, cost_usd=0.25)
        if st == Stage.S9_QA:
            evaluate_missing_qa(self.repo, self.cfg, self.vlm)
            return self._record_stage(
                st, ihash, tokens_in=200, tokens_out=100, cost_usd=0.02
            )
        if st == Stage.S10_ASSEMBLE:
            run_assemble_stage(self.repo, self.cfg, self._allow_partial_assembly)
            return self._record_stage(st, ihash)
        raise ValueError(f"Unsupported stage: {st}")

    def run_until_gate_or_done(
        self,
        story_text: str | None = None,
        auto_approve_gates: bool | None = None,
    ) -> list[StageRun]:
        """Run the pipeline forward from the current state until blocked by an unapproved gate or finished."""
        if auto_approve_gates is not None:
            self._auto_approve_override = auto_approve_gates
            meta = self.repo.get_project_meta()
            if meta is not None:
                self.repo.put_project_meta(
                    meta.model_copy(update={"auto_approve_gates": auto_approve_gates})
                )
        if story_text is not None and not self.repo.get_source_text():
            self.ingest_story(story_text)

        executed: list[StageRun] = []
        for stage in STAGE_ORDER[1:]:
            executed.append(self.run_stage(stage))
            gate_id = GATE_FOR_STAGE.get(str(stage))
            if gate_id:
                require_gate(self.repo, gate_id)
        return executed
