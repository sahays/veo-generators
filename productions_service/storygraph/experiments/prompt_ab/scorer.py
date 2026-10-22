"""Score every successful render with (a) the deployed eval engine and (b) model-free +
independent frame checks, against the V1 spec (the shot's intent) for every variant.

The engine is built exactly like `storygraph.eval.run` except its transcriber uses
`JUDGE_MODEL`: the default flash transcriber returns empty transcripts (see README), which
would mark every scripted line missing for every variant.
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from google import genai

from ...adapters.embeddings import make_embedder
from ...adapters.transcribe import GeminiTranscriber
from ...adapters.vlm import GeminiVLMProvider
from ...config import Config
from ...eval.contracts import EvalInput, EvalReport, LabelledRef
from ...eval.engine import EvalEngine
from ...eval.gate import decide
from ...omni.spec import OmniClipSpec
from ...qa.critic.checks import CriticThresholds
from .contracts import ScoreRecord, ShotCase
from .frame_judge import (
    JUDGE_MODEL,
    FrameVerdict,
    dialogue_score,
    judge_frames,
    transcribe,
)
from .frames import check_clip

logger = logging.getLogger(__name__)
ENGINE_DIMS = (
    "action_adherence",
    "object_permanence",
    "character_consistency",
    "camera_adherence",
    "temporal_consistency",
    "script_adherence",
)


def build_engine(project: str) -> EvalEngine:
    cfg = Config.load(None)
    return EvalEngine(
        vlm=GeminiVLMProvider(cfg.models.critic_vlm),
        gate_cfg=cfg.eval,
        thr=CriticThresholds.from_cfg(cfg.qa),
        embedder=make_embedder(prefer_vertex=True),
        transcriber=GeminiTranscriber(model=JUDGE_MODEL, project=project),
        run_cv=True,
    )


def fetch_refs(case: ShotCase, cache: Path) -> list[LabelledRef]:
    cache.mkdir(parents=True, exist_ok=True)
    refs: list[LabelledRef] = []
    for lbl in case.labels:
        png = cache / f"{lbl.asset_id}.png"
        if not png.exists():
            subprocess.run(
                ["gcloud", "storage", "cp", "-q", lbl.uri, str(png)], check=True
            )
        kind = "setting" if lbl.role == "location" else "identity"
        refs.append(
            LabelledRef(
                label=" & ".join(lbl.names),
                kind=kind,
                entity_names=list(lbl.names),
                png=png.read_bytes(),
            )
        )
    return refs


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def frame_dims(v: FrameVerdict, cuts: tuple[float, ...]) -> dict[str, float | None]:
    objs = [
        float(
            o.max_instances_in_one_frame <= 1
            and not o.vanishes_or_pops_in
            and o.holder_correct
        )
        for o in v.objects
    ]
    return {
        "action.frames": _mean([float(b) for b in v.beats_done]),
        "objects.frames": _mean(objs),
        "character.frames": _mean([c.matches_reference for c in v.characters]),
        "camera.frames": float(v.camera_matches),
        "cuts.ffmpeg": float(not cuts),
        "cuts.judge": float(v.scene_cuts_seen == 0),
    }


def engine_dims(report: EvalReport) -> dict[str, float | None]:
    return {
        f"{d}.eval": (report.results[d].score if d in report.results else None)
        for d in ENGINE_DIMS
    }


class Scorer:
    def __init__(self, cases: list[ShotCase], out: Path, project: str) -> None:
        self.cases = {c.case_id: c for c in cases}
        self.out = out
        self.engine = build_engine(project)
        self.client = genai.Client(vertexai=True, project=project, location="global")
        self.refs = {c.case_id: fetch_refs(c, out / "refs") for c in cases}
        self._lock = threading.Lock()
        (out / "evals").mkdir(exist_ok=True)

    def _engine_eval(self, case: ShotCase, clip: Path) -> tuple[EvalReport, bool]:
        prev = Path(case.prev_frame_path).read_bytes() if case.prev_frame_path else None
        inp = EvalInput(
            clip_path=str(clip),
            spec_json=case.spec_json,
            refs=self.refs[case.case_id],
            prev_last_frame=prev,
            shot_id=clip.stem,
        )
        report = self.engine.evaluate(inp)
        decision, _, _ = decide(report.results, self.engine.gate_cfg, self.engine.thr)
        return report, decision.passed

    def score(self, rec: dict[str, Any]) -> ScoreRecord:
        case, clip = self.cases[rec["case_id"]], Path(rec["clip_path"])
        spec = OmniClipSpec.model_validate_json(case.spec_json)
        fc = check_clip(clip, self.out)
        report, passed = self._engine_eval(case, clip)
        refs = [
            (r.label, r.png) for r in self.refs[case.case_id] if r.kind == "identity"
        ]
        verdict = judge_frames(self.client, spec, Path(fc.frames_dir), refs)
        text = transcribe(self.client, clip)
        dims = {
            **engine_dims(report),
            **frame_dims(verdict, fc.cut_times_s),
            "dialogue.transcript": dialogue_score(spec, text),
        }
        defects = [
            f"{d.severity}:{d.type}:{d.evidence[:140]}"
            for r in report.results.values()
            for d in r.defects
        ]
        out = ScoreRecord(
            rec["case_id"],
            rec["variant"],
            rec["sample"],
            dims,
            report.overall,
            passed,
            len(fc.cut_times_s),
            text,
            defects,
            fc.contact_sheet,
        )
        self._persist(clip.stem, out, report, verdict)
        return out

    def _persist(
        self, stem: str, rec: ScoreRecord, report: EvalReport, v: FrameVerdict
    ) -> None:
        detail = {
            "score": rec.to_dict(),
            "engine": report.model_dump(mode="json"),
            "frames_verdict": v.model_dump(),
        }
        (self.out / "evals" / f"{stem}.json").write_text(
            json.dumps(detail, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        with self._lock, (self.out / "scores.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec.to_dict(), ensure_ascii=False) + "\n")
        logger.info(
            "prompt_ab scored what=%s overall=%.2f why=ab_experiment", stem, rec.overall
        )

    def safe_score(self, rec: dict[str, Any]) -> ScoreRecord | None:
        try:
            return self.score(rec)
        except Exception as exc:  # noqa: BLE001 - one bad clip must not abort the batch
            logger.error(
                "prompt_ab score failed what=%s why=%s", rec.get("clip_path"), exc
            )
            return None


def score_all(cases: list[ShotCase], out: Path, workers: int, project: str) -> None:
    done = set()
    scores = out / "scores.jsonl"
    if scores.exists():
        done = {
            (r["case_id"], r["variant"], r["sample"])
            for r in map(json.loads, scores.read_text(encoding="utf-8").splitlines())
        }
    renders = [
        json.loads(ln) for ln in (out / "renders.jsonl").read_text().splitlines()
    ]
    todo = [
        r
        for r in renders
        if r["ok"] and (r["case_id"], r["variant"], r["sample"]) not in done
    ]
    scorer = Scorer(cases, out, project)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        got = list(pool.map(scorer.safe_score, todo))
    logger.info(
        "prompt_ab score_batch who=scorer what=scored %d/%d why=ab_experiment",
        sum(g is not None for g in got),
        len(todo),
    )
