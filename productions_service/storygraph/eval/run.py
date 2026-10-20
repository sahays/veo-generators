"""Offline eval CLI: `python -m storygraph.eval.run --clip X --spec Y [--prev Z]`.

Prints the `EvalReport` JSON (plus the gate decision) for one clip using the same engine as
the S9 critic. `--mock` uses the deterministic mock VLM and skips network-backed metrics.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..adapters.base import VLMProvider
from ..adapters.embeddings import make_embedder
from ..adapters.media_frames import probe_clip
from ..adapters.mock import MockVLMProvider
from ..adapters.transcribe import GeminiTranscriber
from ..adapters.vlm import GeminiVLMProvider
from ..config import Config
from ..qa.critic.checks import CriticThresholds
from .contracts import EvalInput, LabelledRef
from .engine import EvalEngine
from .gate import decide


def _parse(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="storygraph.eval.run", description=__doc__)
    p.add_argument("--clip", required=True, help="Rendered clip (mp4).")
    p.add_argument("--spec", required=True, help="Compiled OmniClipSpec JSON file.")
    p.add_argument(
        "--prev", help="Previous approved clip (mp4) or its last frame (png)."
    )
    p.add_argument(
        "--ref", action="append", default=[], help="label=path.png (repeatable)."
    )
    p.add_argument("--style", default="", help="Style guide text.")
    p.add_argument(
        "--config", help="Config YAML (defaults to storygraph/config/default.yaml)."
    )
    p.add_argument("--mock", action="store_true", help="Mock VLM, no network metrics.")
    return p.parse_args(argv)


def _prev_frame(path: str | None) -> bytes | None:
    if not path:
        return None
    raw = Path(path).read_bytes()
    return probe_clip(raw).last_frame_png if path.lower().endswith(".mp4") else raw


def _refs(items: list[str]) -> list[LabelledRef]:
    refs: list[LabelledRef] = []
    for item in items:
        label, _, path = item.partition("=")
        kind = "setting" if "setting" in label.lower() else "identity"
        refs.append(LabelledRef(label=label, kind=kind, png=Path(path).read_bytes()))
    return refs


def _engine(cfg: Config, mock: bool) -> EvalEngine:
    vlm: VLMProvider = (
        MockVLMProvider() if mock else GeminiVLMProvider(cfg.models.critic_vlm)
    )
    return EvalEngine(
        vlm=vlm,
        gate_cfg=cfg.eval,
        thr=CriticThresholds.from_cfg(cfg.qa),
        embedder=None if mock else make_embedder(prefer_vertex=True),
        transcriber=None if mock else GeminiTranscriber(),
        run_cv=not mock,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    cfg = Config.load(args.config)
    inp = EvalInput(
        clip_path=args.clip,
        spec_json=Path(args.spec).read_text(encoding="utf-8"),
        refs=_refs(args.ref),
        prev_last_frame=_prev_frame(args.prev),
        style_guide=args.style,
        shot_id=Path(args.clip).stem,
    )
    engine = _engine(cfg, args.mock)
    report = engine.evaluate(inp)
    decision, dims, overall = decide(report.results, engine.gate_cfg, engine.thr)
    out = {
        "report": report.model_dump(mode="json"),
        "gate": {"passed": decision.passed, "reasons": decision.failure_reasons},
        "dimension_scores": [d.model_dump() for d in dims],
        "overall": overall,
    }
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if decision.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
