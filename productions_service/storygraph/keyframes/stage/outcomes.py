"""Terminal shot states for S8_KEYFRAMES: failed sets, manual-edit flags, settled shots.

Every shot the stage touches ends in exactly one recorded state — approved, manual_edit, or
failed (a `KeyframeSet` with `failure_reason`, holding any frames finished before the
failure so a resume continues from there). Recording itself is guarded: if the store write
fails too, the failure is still logged and reported in the stage result.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from ...adapters.governor import ModelCallError
from ...errors import describe_exception
from ...repo import Repo
from ...repo.keyframe_sets import KeyframeSetRepo
from ...schema import Role, Shot
from ...schemas.keyframes import KeyframeSet
from ...shots.repair_state import repair_reset_update

_log = logging.getLogger(__name__)
REASON_CHARS = 300


def failure_text(exc: BaseException) -> str:
    """Short, human reason: governor give-ups read as-is ('quota exhausted after N ...')."""
    text = str(exc) if isinstance(exc, ModelCallError) else describe_exception(exc)
    return text[:REASON_CHARS]


def manual_edit_reasons(ks: KeyframeSet) -> list[str]:
    reasons = [
        f"keyframe t={f.t}: {'; '.join(f.issues[:2])}"
        for f in ks.frames
        if f.status == "manual_edit"
    ]
    if ks.failure_reason:
        reasons.insert(0, f"keyframes failed: {ks.failure_reason}")
    return reasons


def flag_manual_edit(repo: Repo, shot: Shot, ks: KeyframeSet) -> None:
    """Shot repair policy: keyframes that fail every retry block render until edited."""
    update = {"needs_manual_edit": True, "manual_edit_reasons": manual_edit_reasons(ks)}
    repo.put_shot(shot.model_copy(update=update))


def settle_shot(
    repo: Repo, shot: Shot, ks: KeyframeSet, stale_reason: str | None
) -> None:
    """New keyframes for `shot`: fresh repair budget (clears an earlier failure flag),
    stale when a clip rendered from older keyframes exists, flagged if frames need edits."""
    update = repair_reset_update()
    if stale_reason:
        update |= {"stale": True, "stale_reason": stale_reason}
    if ks.needs_manual_edit:
        update |= {
            "needs_manual_edit": True,
            "manual_edit_reasons": manual_edit_reasons(ks),
        }
    repo.put_shot(shot.model_copy(update=update))


def failed_set(shot: Shot, reason: str, partial: KeyframeSet | None) -> KeyframeSet:
    """The failed version: `partial` (frames done before the failure) or an empty set."""
    base = partial or KeyframeSet(
        id=f"kfs_{shot.id}",
        created_by=Role.PIPELINE,
        shot_id=shot.id,
        scene_id=shot.scene_id,
        clip_index=shot.clip_index or 0,
        plan_hash="",
        duration_s=shot.duration_s,
    )
    update = {
        "needs_manual_edit": True,
        "reason": "S8_KEYFRAMES failed",
        "failure_reason": reason,
    }
    return base.model_copy(update=update)


def record_failure(
    repo: Repo, shot: Shot, reason: str, partial: KeyframeSet | None = None
) -> str:
    """Persist the failed set + blocked shot; returns `reason` even if the write fails."""
    try:
        ks = KeyframeSetRepo(repo.store).create(failed_set(shot, reason, partial))
        flag_manual_edit(repo, shot, ks)
    except Exception as exc:  # noqa: BLE001 - the failure must still reach the result
        _log_event(repo, shot, logging.CRITICAL, "failure not persisted", str(exc))
    kept = len(partial.frames) if partial else 0
    _log_event(repo, shot, logging.ERROR, f"shot failed ({kept} frames kept)", reason)
    return reason


def _log_event(repo: Repo, shot: Shot, level: int, what: str, why: str) -> None:
    _log.log(
        level,
        f"S8_KEYFRAMES {what}",
        extra={
            "who": "storygraph.keyframes.stage",
            "where": f"project/{repo.project_id}/{shot.scene_id}/{shot.id}",
            "what": what,
            "when": datetime.now(UTC).isoformat(),
            "why": why[:REASON_CHARS],
            "how": "failed KeyframeSet recorded + shot flagged; resume re-derives it",
        },
    )
