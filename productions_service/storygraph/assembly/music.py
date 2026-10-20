"""Per-scene music bed for final assembly.

Music is not generated per clip (the Omni prompt says "No music."); instead the `MusicCue`
of each scene supplies an audio asset (`MusicCue.audio_asset_id` -> `Asset(kind="audio")`)
that is mixed as one continuous score under the stitched video, ducked beneath clip audio
and crossfaded at scene boundaries. No music generator exists yet, so most projects take the
logged `no music assets; skipped` path; the mixer is an injectable `MusicMixer`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from ..config import AssemblyCfg
from ..repo import Repo
from .readiness import ReadyShot

logger = logging.getLogger(__name__)

DurationProbe = Callable[[bytes], float | None]


@dataclass(frozen=True)
class SceneSegment:
    """A contiguous run of stitched clips from one scene and its score audio (if any)."""

    scene_id: str
    start_s: float
    duration_s: float
    audio: bytes | None


class MusicMixer(Protocol):
    def __call__(
        self, video: bytes, segments: list[SceneSegment], cfg: AssemblyCfg
    ) -> bytes: ...


def _log_ctx(
    what: str, why: str, project_id: str, **fields: object
) -> dict[str, object]:
    return {
        "who": "storygraph.assembly",
        "where": "assembly.music",
        "what": what,
        "why": why,
        "how": "MusicCue.audio_asset_id -> MusicMixer",
        "when": datetime.now(UTC).isoformat(),
        "project_id": project_id,
        **fields,
    }


def _scene_audio(repo: Repo, scene_id: str) -> bytes | None:
    """Return the first readable audio asset bytes among the scene's MusicCues."""
    for cue in repo.list_music_cues(scene_id=scene_id):
        asset = repo.get_asset(cue.audio_asset_id) if cue.audio_asset_id else None
        if asset is not None and asset.kind == "audio" and asset.uri:
            return repo.blobs.get_bytes(asset.uri)
    return None


def _scene_ids(repo: Repo, ready: list[ReadyShot]) -> list[str]:
    ids: list[str] = []
    for r in ready:
        shot = repo.get_shot(r.shot_id)
        ids.append(shot.scene_id if shot else "")
    return ids


def _durations(
    repo: Repo, ready: list[ReadyShot], clips: list[bytes], probe: DurationProbe
) -> list[float]:
    out: list[float] = []
    for r, clip in zip(ready, clips, strict=True):
        measured = probe(clip)
        shot = repo.get_shot(r.shot_id)
        out.append(measured or (shot.duration_s if shot else 0.0))
    return out


def build_scene_segments(
    scene_ids: list[str], durations: list[float], audio: dict[str, bytes | None]
) -> list[SceneSegment]:
    """Group consecutive clips by scene into timed segments (single O(N) pass)."""
    segments: list[SceneSegment] = []
    cursor = 0.0
    for sid, dur in zip(scene_ids, durations, strict=True):
        if segments and segments[-1].scene_id == sid:
            last = segments[-1]
            segments[-1] = SceneSegment(
                sid, last.start_s, last.duration_s + dur, last.audio
            )
        else:
            segments.append(SceneSegment(sid, cursor, dur, audio.get(sid)))
        cursor += dur
    return segments


def apply_music_bed(
    repo: Repo,
    ready: list[ReadyShot],
    clips: list[bytes],
    video: bytes,
    cfg: AssemblyCfg,
    mixer: MusicMixer | None,
    probe: DurationProbe,
) -> bytes:
    """Mix scene scores under `video` when audio assets exist; otherwise return it unchanged."""
    project_id = repo.project_id
    if not cfg.music_enabled or mixer is None:
        why = (
            "music disabled in config"
            if not cfg.music_enabled
            else "no mixer available"
        )
        logger.info(
            "Music bed skipped", extra=_log_ctx("music_skipped", why, project_id)
        )
        return video
    scene_ids = _scene_ids(repo, ready)
    audio = {sid: _scene_audio(repo, sid) for sid in dict.fromkeys(scene_ids)}
    if not any(audio.values()):
        logger.info(
            "no music assets; skipped",
            extra=_log_ctx(
                "music_skipped",
                "no MusicCue has an audio asset (no music generator configured)",
                project_id,
                scene_ids=list(audio),
            ),
        )
        return video
    segments = build_scene_segments(
        scene_ids, _durations(repo, ready, clips, probe), audio
    )
    mixed = mixer(video, segments, cfg)
    logger.info(
        "Music bed mixed under final video",
        extra=_log_ctx(
            "music_mixed",
            "MusicCue audio assets present",
            project_id,
            scored_scene_ids=[s.scene_id for s in segments if s.audio],
            silent_scene_ids=[s.scene_id for s in segments if not s.audio],
        ),
    )
    return mixed
