"""Focused frame judge for the keyframe experiment (one structured Gemini call per clip).

Frames are sampled at 1 fps; the judge counts, per frame, the instances of each tracked
object (wooden chest, blue cabinet, ...), whether each character is present and wearing
their reference outfit, extra characters, and whether each scripted beat happens. A second
call compares the last frame of shot k with the first frame of shot k+1 (continuity).
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Sequence
from pathlib import Path
from typing import TypeVar

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel, ValidationError

from .contracts import ClipObservation, ContinuityObs

T = TypeVar("T", bound=BaseModel)
JUDGE_MODEL = "gemini-3.1-pro-preview"


def frames_1fps(clip: Path, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(clip),
            "-vf",
            "fps=1,scale=640:-2",
        ]
        + [str(out_dir / "f_%02d.jpg")],
        check=False,
        capture_output=True,
        timeout=120,
    )
    return sorted(out_dir.glob("f_*.jpg"))


def _ask(
    client: genai.Client, parts: list[object], schema: type[T], tries: int = 3
) -> T:
    """Structured call; a truncated/invalid JSON answer is retried (`tries` total)."""
    cfg = types.GenerateContentConfig(
        temperature=0.0,
        response_mime_type="application/json",
        response_schema=schema,
        max_output_tokens=32768,
    )
    for attempt in range(tries):
        try:
            resp = client.models.generate_content(
                model=JUDGE_MODEL, contents=parts, config=cfg
            )
            return schema.model_validate_json(resp.text or "{}")
        except (ValidationError, genai_errors.APIError) as exc:
            api = isinstance(exc, genai_errors.APIError)
            if attempt + 1 == tries or (api and exc.code not in (429, 500, 503)):
                raise
            time.sleep(30 * (attempt + 1))  # quota / capacity back-off
    raise RuntimeError("unreachable")


def observe_clip(
    client: genai.Client,
    frames: Sequence[Path],
    beats: Sequence[str],
    objects: Sequence[str],
    characters: Sequence[tuple[str, str, bytes]],
) -> ClipObservation:
    """Per-frame counts + beat adherence; `characters` = (name, outfit, reference png)."""
    parts: list[object] = []
    for idx, frame in enumerate(frames):
        parts += [
            f"Frame {idx}",
            types.Part.from_bytes(data=frame.read_bytes(), mime_type="image/jpeg"),
        ]
    for name, _, png in characters:
        parts += [
            f"Reference: {name}",
            types.Part.from_bytes(data=png, mime_type="image/png"),
        ]
    beat_list = "\n".join(f"{i + 1}. {b}" for i, b in enumerate(beats))
    outfits = "\n".join(f"- {n}: {o}" for n, o, _ in characters)
    parts.append(
        "Frames are sampled at 1 fps from one generated clip, in order. Judge strictly.\n"
        f"For EVERY frame, count separate visible instances of each object: {', '.join(objects)}.\n"
        f"For every frame and character, report present and outfit_matches (vs reference/outfit):\n{outfits}\n"
        "extra_characters = people/creatures not listed.\n"
        f"beats_done: for each beat in order, did it visibly happen?\n{beat_list}"
    )
    return _ask(client, parts, ClipObservation)


def continuity(
    client: genai.Client, last_frame: Path, first_frame: Path
) -> ContinuityObs:
    parts: list[object] = [
        "Image A: last frame of shot 1.",
        types.Part.from_bytes(data=last_frame.read_bytes(), mime_type="image/jpeg"),
        "Image B: first frame of the next shot of the same continuous scene (camera may change).",
        types.Part.from_bytes(data=first_frame.read_bytes(), mime_type="image/jpeg"),
        (
            "Are the characters, outfits, objects (counts and placement) and room layout the same "
            "story state? Score 0-1 and list concrete differences."
        ),
    ]
    return _ask(client, parts, ContinuityObs)
