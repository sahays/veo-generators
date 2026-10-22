"""Repair routing: state/prop/wardrobe defects go to keyframes first; motion re-renders only."""

from __future__ import annotations

from storygraph.config import Config
from storygraph.keyframes.stage.ground_truth import keyframe_defects
from storygraph.pipeline.keyframes.repair import keyframe_route_applies
from storygraph.schema import QADefect, QAReport


def _report(*types: str) -> QAReport:
    return QAReport(
        passed=False,
        defects=[
            QADefect(type=t, severity="high", subject="x", evidence=f"{t} seen")
            for t in types
        ],
    )


def test_state_defects_select_keyframe_route_motion_defects_do_not() -> None:
    cfg = Config()
    cfg.video.render_strategy = "keyframe_anchored"
    state = _report("extra_object", "wardrobe_mismatch", "step_not_done")
    motion = _report(
        "step_not_done",
        "unscripted_action",
        "camera_mismatch",
        "hard_cut",
        "line_missing",
    )
    assert keyframe_route_applies(cfg, state)
    assert not keyframe_route_applies(cfg, motion)
    assert [d.split(" ")[0] for d in keyframe_defects(state)] == [
        "extra_object",
        "wardrobe_mismatch",
    ]


def test_direct_strategy_never_routes_to_keyframes() -> None:
    cfg = Config()
    cfg.video.render_strategy = "direct"
    assert not keyframe_route_applies(cfg, _report("missing_object", "object_state"))
