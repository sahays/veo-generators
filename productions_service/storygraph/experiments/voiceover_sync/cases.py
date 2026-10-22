"""Load exported production data into typed experiment cases and fixed cast voices."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ...audio.voice.registry import DEFAULT_TTS_MODEL, assign_cast_voices
from ...audio.voice.timing import SpeechLine
from ...schema import Entity
from ...schemas.voice import VoiceProfile
from .contracts import ClipCase


def _rows(export_dir: Path, name: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = json.loads(
        (export_dir / f"{name}.json").read_text("utf-8")
    )
    return rows


def load_cast(export_dir: Path) -> tuple[list[Entity], str]:
    """Entities (export `_id` dropped) and the story source text."""
    cast = [
        Entity.model_validate({k: v for k, v in r.items() if k != "_id"})
        for r in _rows(export_dir, "entities")
    ]
    meta = {r.get("_id"): r for r in _rows(export_dir, "meta")}
    return cast, str(meta.get("source", {}).get("text", ""))


def load_cases(export_dir: Path, clips_dir: Path, cast: list[Entity]) -> list[ClipCase]:
    """One case per downloaded clip (`<shot_id>_att<n>_<hash>.mp4`) with its scripted lines."""
    names = {e.id: e.canonical_name for e in cast}
    by_shot: dict[str, list[SpeechLine]] = {}
    lines = sorted(
        _rows(export_dir, "dialogue_lines"),
        key=lambda r: (r["scene_id"], r["order_in_scene"]),
    )
    for r in lines:
        by_shot.setdefault(r["shot_id"], []).append(
            SpeechLine(
                line_id=r["id"],
                speaker_id=r["speaker_id"],
                speaker_name=names.get(r["speaker_id"], r["speaker_id"]),
                lang=r.get("language", "en"),
                text=r["text"],
                delivery=r.get("delivery") or "",
            )
        )
    cases: list[ClipCase] = []
    for path in sorted(clips_dir.glob("*.mp4")):
        shot_id = path.stem.split("_att")[0]
        if shot_id in by_shot:
            cases.append(ClipCase(path.stem, shot_id, path, by_shot[shot_id]))
    return cases


def cast_voices(
    cast: list[Entity], source: str, cases: list[ClipCase]
) -> dict[str, VoiceProfile]:
    """Deterministic fixed voices for every speaker appearing in the cases."""
    speaker_ids = {ln.speaker_id for c in cases for ln in c.lines}
    speakers = [e for e in cast if e.id in speaker_ids]
    return assign_cast_voices(speakers, cast, source, DEFAULT_TTS_MODEL)
