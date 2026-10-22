"""Independent frame-based judge: one structured Gemini call over the 3 fps frames.

A second opinion next to the deployed eval engine. The checklist is derived from the V1
spec (the shot's intent), so every variant is judged against the same ground truth.
The dialogue check uses a separate free-text transcription (no response schema), because
the production transcriber was found to return empty transcripts on clips with clear speech.
"""

from __future__ import annotations

from pathlib import Path

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from ...eval.metrics.text import char_similarity
from ...omni.spec import OmniClipSpec
from .variants.phrasing import SHOT_SIZES, Names, step_text

JUDGE_MODEL = "gemini-3.1-pro-preview"
MAX_FRAMES = 30


class ObjectSeen(BaseModel):
    name: str
    max_instances_in_one_frame: int = Field(ge=0)
    vanishes_or_pops_in: bool
    holder_correct: bool


class CharacterSeen(BaseModel):
    name: str
    matches_reference: float = Field(ge=0.0, le=1.0)


class FrameVerdict(BaseModel):
    beats_done: list[bool]
    objects: list[ObjectSeen]
    characters: list[CharacterSeen]
    camera_matches: bool
    scene_cuts_seen: int = Field(ge=0)
    notes: str = ""


def _checklist(spec: OmniClipSpec) -> str:
    names = Names.of(spec)
    beats = "\n".join(
        f"{i + 1}. {step_text(s, names)}" for i, s in enumerate(spec.sequence or [])
    )
    objs = ", ".join(o.name for o in spec.objects or [] if o.in_frame)
    chars = ", ".join(s.name for s in spec.subjects or [])
    cam = spec.camera
    return (
        "Frames are sampled at 3 fps from one generated clip, in order. Reference images "
        "follow the frames. Judge strictly from what is visible.\n"
        f"BEATS (in order):\n{beats}\nOBJECTS (each should exist exactly once): {objs}\n"
        f"CHARACTERS (compare to their reference image): {chars}\n"
        f"CAMERA: {SHOT_SIZES.get(cam.size.upper(), cam.size)}, angle {cam.angle}, "
        f"movement {cam.move}.\nReturn beats_done in beat order; for every object the max "
        "copies visible in any single frame, whether it vanishes/pops in, and whether the "
        "holder matches the beats; scene_cuts_seen = hard cuts to a different shot."
    )


def _image_parts(frames: list[Path], refs: list[tuple[str, bytes]]) -> list[object]:
    step = max(1, len(frames) // MAX_FRAMES + (1 if len(frames) % MAX_FRAMES else 0))
    parts: list[object] = [
        types.Part.from_bytes(data=f.read_bytes(), mime_type="image/jpeg")
        for f in frames[::step]
    ]
    for label, png in refs:
        parts += [
            f"Reference: {label}",
            types.Part.from_bytes(data=png, mime_type="image/png"),
        ]
    return parts


def judge_frames(
    client: genai.Client,
    spec: OmniClipSpec,
    frames_dir: Path,
    refs: list[tuple[str, bytes]],
) -> FrameVerdict:
    frames = sorted(frames_dir.glob("f_*.jpg"))
    resp = client.models.generate_content(
        model=JUDGE_MODEL,
        contents=[*_image_parts(frames, refs), _checklist(spec)],
        config=types.GenerateContentConfig(
            temperature=0.0,
            response_mime_type="application/json",
            response_schema=FrameVerdict,
        ),
    )
    return FrameVerdict.model_validate_json(resp.text or "{}")


TRANSCRIBE_PROMPT = (
    "Transcribe every spoken word in this video verbatim in its original script "
    "(Devanagari for Hindi; never translate). One utterance per line. If nobody speaks, "
    "reply exactly NO_SPEECH."
)


def transcribe(client: genai.Client, clip: Path) -> str:
    resp = client.models.generate_content(
        model=JUDGE_MODEL,
        contents=[
            types.Part.from_bytes(data=clip.read_bytes(), mime_type="video/mp4"),
            TRANSCRIBE_PROMPT,
        ],
        config=types.GenerateContentConfig(temperature=0.0),
    )
    return (resp.text or "").strip()


def dialogue_score(spec: OmniClipSpec, transcript: str) -> float | None:
    """Mean best char-similarity of each scripted line vs any transcript line (None: no lines)."""
    lines = [s.text for s in spec.speech or []]
    if not lines:
        return None
    heard = [
        ln for ln in transcript.splitlines() if ln.strip() and ln.strip() != "NO_SPEECH"
    ]
    joined = " ".join(heard)
    sims = [
        max([char_similarity(t, h) for h in [*heard, joined]] or [0.0]) for t in lines
    ]
    return sum(sims) / len(sims)
