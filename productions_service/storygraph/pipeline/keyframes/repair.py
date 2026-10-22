"""Keyframe-first repair route: state / prop / wardrobe defects go back to S8_KEYFRAMES.

When a clip fails QA with defects the keyframes can fix (duplicate or missing props, wrong
object state, wardrobe/identity drift, continuity breaks) and a keyframe render strategy is
active, the shot's keyframes are re-derived from the first editable second with the defects
as the edit instruction (cheap image edits), and only then is the clip re-rendered. Motion,
action, camera, physics and audio defects keep the existing render/spec routes.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from ...adapters.base import ImageGenerator
from ...adapters.gemini_image import GeminiImageGenerator
from ...adapters.mock import MockImageGenerator
from ...config import Config
from ...errors import NotFound, StoryGraphError, ValidationFailed
from ...keyframes.stage.ground_truth import keyframe_defects
from ...keyframes.stage.regenerate import regenerate_from
from ...repo.keyframe_sets import KeyframeSetRepo
from ...schema import QAReport
from .stage_adapter import keyframe_deps
from ..shot_attempt import RenderDeps

_log = logging.getLogger(__name__)


def keyframe_route_applies(cfg: Config, report: QAReport) -> bool:
    """True when keyframes drive rendering and the failure includes a state defect."""
    return cfg.video.render_strategy != "direct" and bool(keyframe_defects(report))


def _image_generator(cfg: Config) -> ImageGenerator:
    if cfg.image.provider == "mock":
        return MockImageGenerator()
    return GeminiImageGenerator(model=cfg.image.model)


def first_editable(repo_sets: KeyframeSetRepo, shot_id: str) -> int:
    """Frame 0 when owned by this clip, else 1 (frame 0 is the previous clip's last frame)."""
    ks = repo_sets.active_for_shot(shot_id)
    if ks is None or not ks.frames:
        raise NotFound(f"no keyframes for {shot_id}")
    return 1 if ks.frames[0].shared_from else 0


def repair_keyframes(deps: RenderDeps, shot_id: str, report: QAReport) -> bool:
    """Re-derive the shot's keyframes against its state defects; False when not possible."""
    defects = keyframe_defects(report)
    instruction = "Fix these defects seen in the rendered clip: " + "; ".join(
        defects[:4]
    )
    kf = keyframe_deps(deps.repo, deps.cfg, _image_generator(deps.cfg), deps.vlm)
    try:
        start = first_editable(KeyframeSetRepo(deps.repo.store), shot_id)
        ks = regenerate_from(kf, shot_id, start, instruction, reset_repair=False)
    except (NotFound, ValidationFailed, StoryGraphError) as exc:
        _log_route(shot_id, False, str(exc), defects)
        return False
    _log_route(shot_id, True, f"keyframe set {ks.id} from t={start}", defects)
    return True


def _log_route(shot_id: str, ok: bool, how: str, defects: list[str]) -> None:
    _log.info(
        "keyframe repair route",
        extra={
            "who": "storygraph.pipeline.keyframe_repair",
            "where": f"shot_repair:{shot_id}",
            "what": "keyframes re-derived" if ok else "keyframe route unavailable",
            "when": datetime.now(UTC).isoformat(),
            "why": "state/prop/wardrobe defects: " + "; ".join(defects[:3]),
            "how": how,
            "shot_id": shot_id,
        },
    )
