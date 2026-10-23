"""Deterministic Mock Adapters for offline testing and CI verification."""

from __future__ import annotations

import hashlib
import io
import re
import shutil
import subprocess
import tempfile
import textwrap
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from PIL import Image, ImageDraw
from pydantic import BaseModel

from ..compile import Package
from ..config import VideoProviderCfg
from ..schema import QAReport

T = TypeVar("T", bound=BaseModel)


class MockImageGenerator:
    """Generates deterministic valid PNG images with embedded prompt digest and color coding."""

    def __init__(self, width: int = 640, height: int = 360) -> None:
        self.width = width
        self.height = height
        self.calls: list[dict[str, Any]] = []

    def generate(
        self,
        prompt: str,
        reference_images: list[bytes] | None = None,
        aspect_ratio: str = "16:9",
        seed: int = 42,
    ) -> bytes:
        self.calls.append(
            {
                "prompt": prompt,
                "ref_count": len(reference_images or []),
                "aspect_ratio": aspect_ratio,
                "seed": seed,
            }
        )
        digest = hashlib.sha256(f"{prompt}:{seed}".encode()).digest()
        w, h = (360, 640) if aspect_ratio == "9:16" else (self.width, self.height)
        anchored = _anchored_copy(prompt, reference_images, (w, h), digest)
        if anchored is not None:
            return anchored
        color = (30 + (digest[0] % 160), 40 + (digest[1] % 160), 60 + (digest[2] % 160))
        img = Image.new("RGB", (w, h), color=color)
        draw = ImageDraw.Draw(img)
        draw.rectangle([(12, 12), (w - 12, h - 12)], outline=(245, 158, 11), width=3)
        draw.text((24, 24), f"SEED {seed}", fill=(255, 255, 255))
        draw.text((24, 48), prompt[:64], fill=(240, 240, 240))
        if len(prompt) > 64:
            draw.text((24, 70), prompt[64:128], fill=(210, 210, 210))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()


# S8_KEYFRAMES requests anchored on a locked scene plate (image 1) must reproduce it.
_ANCHOR_MARK = "LOCKED SCENE PLATE"


def _anchored_copy(
    prompt: str, refs: list[bytes] | None, size: tuple[int, int], digest: bytes
) -> bytes | None:
    """The anchor image (resized) with one digest pixel, or None when not anchored."""
    if _ANCHOR_MARK not in prompt or not refs:
        return None
    try:
        img = Image.open(io.BytesIO(refs[0])).convert("RGB").resize(size)
    except (OSError, ValueError):
        return None
    img.putpixel(
        (digest[3] % size[0], digest[4] % size[1]), (digest[5], digest[6], digest[7])
    )
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _render_slate_image(package: Package, digest: bytes) -> Image.Image:
    """Render a deterministic storyboard slate image for `package`."""
    w, h = (360, 640) if package.aspect_ratio == "9:16" else (640, 360)
    bg = (20 + (digest[0] % 80), 28 + (digest[1] % 80), 45 + (digest[2] % 90))
    img = Image.new("RGB", (w, h), color=bg)
    draw = ImageDraw.Draw(img)
    draw.rectangle([(8, 8), (w - 8, h - 8)], outline=(16, 185, 129), width=3)
    draw.rectangle([(8, 8), (w - 8, 44)], fill=(15, 23, 42))
    header = (
        f"SHOT: {package.shot_id}  |  {package.duration_s:.1f}s  |  SEED {package.seed}"
    )
    draw.text((18, 20), header[:72], fill=(52, 211, 153))

    y = 58
    max_chars = 42 if w < h else 78
    for raw_line in package.compiled_prompt.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        for wrapped in textwrap.wrap(line, width=max_chars)[:2]:
            if y <= h - 28:
                draw.text((20, y), wrapped, fill=(241, 245, 249))
                y += 18
        if y > h - 28:
            break
    return img


def _encode_slate_mp4(img: Image.Image, duration_s: float) -> bytes | None:
    """Encode `img` into a short H.264 MP4 clip using ffmpeg if available."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        frame_path = tmp_path / "slate.png"
        out_path = tmp_path / "clip.mp4"
        img.save(frame_path, format="PNG")
        clip_dur = max(1.0, min(float(duration_s or 2.0), 4.0))
        cmd = [
            "ffmpeg",
            "-y",
            "-loop",
            "1",
            "-framerate",
            "5",
            "-i",
            str(frame_path),
            "-t",
            f"{clip_dur:.1f}",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-tune",
            "stillimage",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(out_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, timeout=15, check=False)
        if (
            proc.returncode == 0
            and out_path.is_file()
            and out_path.stat().st_size > 256
        ):
            return out_path.read_bytes()
    return None


class MockVideoGenerator:
    """Generates deterministic browser-playable H.264 MP4 storyboard clips (or minimal ISO container if ffmpeg unavailable)."""

    def __init__(
        self,
        caps: VideoProviderCfg | None = None,
        fail_first_attempt_shots: set[str] | None = None,
    ) -> None:
        self.caps = caps or VideoProviderCfg()
        self.fail_first_attempt_shots = fail_first_attempt_shots or set()
        self.calls: list[Package] = []

    def generate(self, package: Package) -> bytes:
        self.calls.append(package)
        digest = hashlib.sha256(package.package_hash.encode("utf-8")).digest()
        if shutil.which("ffmpeg"):
            try:
                img = _render_slate_image(package, digest)
                mp4_bytes = _encode_slate_mp4(img, package.duration_s)
                if mp4_bytes is not None:
                    return mp4_bytes
            except (OSError, subprocess.SubprocessError):
                mp4_bytes = None

        return (
            b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"
            + b"\x00\x00\x00\x28mdat"
            + digest
        )


class MockVLMProvider:
    """Deterministic VLM provider that returns structured Pydantic responses."""

    def __init__(
        self,
        custom_responder: Callable[[list[bytes], str, type[BaseModel]], BaseModel]
        | None = None,
        fail_shots_once: set[str] | None = None,
    ) -> None:
        self.custom_responder = custom_responder
        self.fail_shots_once = set(fail_shots_once or set())
        self._seen_shots: set[str] = set()
        self.calls: list[dict[str, Any]] = []

    def _consume_fail_once(self, prompt: str) -> bool:
        """True exactly once per shot listed in `fail_shots_once` (scripted first failure)."""
        shot_match = re.search(r"shot_id=([A-Za-z0-9_]+)", prompt)
        shot_id = shot_match.group(1) if shot_match else ""
        if shot_id in self.fail_shots_once and shot_id not in self._seen_shots:
            self._seen_shots.add(shot_id)
            return True
        return False

    def _build_qa_report(self, prompt: str) -> QAReport:
        if self._consume_fail_once(prompt):
            return QAReport(
                face_similarity={"default": 0.55},
                wardrobe_match=0.60,
                setting_match=0.85,
                action_achieved=0.60,
                continuity_prev_shot=0.80,
                dialogue_wer=0.05,
                artifact_flags=["wardrobe_mismatch_on_attempt_1"],
                passed=False,
                failure_reasons=["Wardrobe match below threshold on first attempt"],
                suggested_fix="retry_seed",
            )
        return QAReport(
            face_similarity={"default": 0.91},
            wardrobe_match=0.92,
            setting_match=0.94,
            action_achieved=0.90,
            continuity_prev_shot=0.92,
            dialogue_wer=0.02,
            artifact_flags=[],
            passed=True,
            failure_reasons=[],
            suggested_fix="none",
        )

    def review(
        self,
        images: list[bytes],
        prompt: str,
        schema: type[T],
    ) -> T:
        self.calls.append(
            {"image_count": len(images), "prompt": prompt, "schema": schema.__name__}
        )
        if self.custom_responder is not None:
            return self.custom_responder(images, prompt, schema)  # type: ignore[return-value]

        if schema is QAReport or schema.__name__ == "QAReport":
            return self._build_qa_report(prompt)  # type: ignore[return-value]
        if hasattr(schema, "mock_response"):
            # Scripted failures (fail_shots_once / patched _build_qa_report) surface as a
            # legacy QAReport, which the critic grades via its legacy branch.
            legacy = self._build_qa_report(prompt)
            if not legacy.passed:
                return legacy  # type: ignore[return-value]
            return schema.mock_response(prompt)  # type: ignore[attr-defined]

        if "approved" in schema.model_fields:
            return schema.model_validate(
                {
                    "approved": True,
                    "qa_notes": "Visual consistency verified against StyleGuide and Appearance.",
                    "refined_visual_description": None,
                }
            )
        return schema.model_validate({})


class MockTTSProvider:
    def synthesize(self, text: str, voice_profile_id: str) -> bytes:
        digest = hashlib.sha256(f"{voice_profile_id}:{text}".encode()).digest()
        return b"RIFF\x24\x00\x00\x00WAVEfmt " + digest


class MockLLMClient:
    """Scripted/heuristic LLM client for deterministic offline agent runs."""

    def __init__(
        self,
        scripted_responses: dict[str, list[Any]] | None = None,
    ) -> None:
        self.scripted_responses: dict[str, list[Any]] = {
            k: list(v) for k, v in (scripted_responses or {}).items()
        }
        self.calls: list[dict[str, Any]] = []

    def pop_response(self, role_key: str) -> Any | None:
        queue = self.scripted_responses.get(role_key)
        if queue:
            return queue.pop(0)
        return None
