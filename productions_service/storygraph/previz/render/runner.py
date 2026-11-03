"""Headless Blender runner: PrevizScene -> layout.json -> `blender -b -P build_scene.py` -> MP4.

Never raises for render problems: every failure mode (binary missing, timeout, non-zero
exit, missing output, invalid scene) comes back as a typed `PrevizRenderFailure`.
"""

from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from storygraph.schemas.previz_scene import PrevizScene

from .build_scene import BUILD_SCENE_VERSION

logger = logging.getLogger(__name__)

BUILD_SCENE_PATH = Path(__file__).with_name("build_scene.py")
STDERR_TAIL_CHARS = 2000
VERSION_TIMEOUT_S = 30.0
MAX_DURATION_S = 120.0
MAX_PIXELS = 1920 * 1080
OUTPUT_NAME = "previz.mp4"
LAYOUT_NAME = "layout.json"
PASSES_DIR = (
    "passes"  # build_scene writes passes/{ids.json,object_id/,depth/} next to the MP4
)
# Failures where the binary never ran (or hung): probing `--version` would only add latency.
_NO_VERSION_PROBE: frozenset[str] = frozenset(
    {"binary_missing", "invalid_scene", "timeout"}
)

FailureKind = Literal[
    "binary_missing", "timeout", "nonzero_exit", "no_output", "invalid_scene"
]


class PrevizRenderFailure(BaseModel):
    """Why a render produced no usable MP4."""

    kind: FailureKind
    message: str


@dataclass(frozen=True)
class RenderResult:
    """Outcome of one Blender render (ok XOR failure)."""

    ok: bool
    mp4_path: Path | None
    seconds: float
    blender_version: str | None
    stderr_tail: str
    failure: PrevizRenderFailure | None = None
    pass_dir: Path | None = None  # set when render.passes was requested and written

    @property
    def failure_text(self) -> str | None:
        """'kind: message' for logs/UI; None when the render succeeded."""
        return (
            None
            if self.failure is None
            else f"{self.failure.kind}: {self.failure.message}"
        )


@dataclass(frozen=True)
class _ProcessOutcome:
    returncode: int | None  # None => killed on timeout
    output: str


def validate_scene(scene: PrevizScene) -> str | None:
    """Return a reason the scene cannot be rendered, or None if it is renderable."""
    settings = scene.render
    if not 0 < scene.blocking.duration_s <= MAX_DURATION_S:
        return f"duration_s must be in (0, {MAX_DURATION_S}], got {scene.blocking.duration_s}"
    if not 1 <= settings.fps <= 60:
        return f"fps must be in [1, 60], got {settings.fps}"
    if (
        settings.width <= 0
        or settings.height <= 0
        or settings.width * settings.height > MAX_PIXELS
    ):
        return f"resolution {settings.width}x{settings.height} out of range"
    if settings.width % 2 or settings.height % 2:
        return f"H.264 needs even dimensions, got {settings.width}x{settings.height}"
    return None


def _tail(text: str) -> str:
    return text[-STDERR_TAIL_CHARS:]


def _decode(raw: bytes | str | None) -> str:
    if raw is None:
        return ""
    return raw if isinstance(raw, str) else raw.decode("utf-8", errors="replace")


def run_process(
    cmd: list[str], timeout_s: float, cwd: Path | None = None
) -> _ProcessOutcome:
    """Run `cmd` in its own process group (stdout+stderr merged); kill the group on timeout."""
    proc = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        out, _ = proc.communicate(timeout=timeout_s)
        return _ProcessOutcome(proc.returncode, _decode(out))
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        out, _ = proc.communicate()
        return _ProcessOutcome(None, _decode(out))


class BlenderRunner:
    """Renders PrevizScene greybox clips with a headless Blender binary."""

    def __init__(self, binary: str | None = None, timeout_s: float = 180.0) -> None:
        self.binary = binary or os.environ.get("BLENDER_BIN") or "blender"
        self.timeout_s = timeout_s
        self._version: str | None = None

    def resolve(self) -> str | None:
        """Absolute path of the Blender executable, or None if it is not installed."""
        found = shutil.which(self.binary)
        if found:
            return found
        path = Path(self.binary)
        return str(path) if path.is_file() and os.access(path, os.X_OK) else None

    def version(self) -> str | None:
        """First line of `blender --version` (e.g. 'Blender 4.2.23 LTS'); None if unavailable."""
        if self._version is not None:
            return self._version
        binary = self.resolve()
        if binary is None:
            return None
        try:
            outcome = run_process([binary, "--version"], VERSION_TIMEOUT_S)
        except OSError:
            return None
        lines = [
            ln.strip()
            for ln in outcome.output.splitlines()
            if ln.strip().startswith("Blender")
        ]
        self._version = lines[0] if outcome.returncode == 0 and lines else None
        return self._version

    def command(self, binary: str, layout: Path, out: Path) -> list[str]:
        """Blender argv: background, factory settings, no audio, script exit code on error."""
        return [
            binary, "-b", "--factory-startup", "-noaudio", "--python-exit-code", "3",
            "-P", str(BUILD_SCENE_PATH), "--", str(layout), str(out),
        ]  # fmt: skip

    def render(
        self, scene: PrevizScene, workdir: Path, assets: dict[str, Path] | None = None
    ) -> RenderResult:
        """Copy `assets` (file name -> source) + layout.json into `workdir`, render, classify."""
        started = time.monotonic()
        reason = validate_scene(scene) or prepare_workdir(scene, workdir, assets or {})
        if reason is not None:
            failure = PrevizRenderFailure(kind="invalid_scene", message=reason)
            return self._finish(scene, started, None, "", failure)
        binary = self.resolve()
        if binary is None:
            failure = PrevizRenderFailure(
                kind="binary_missing",
                message=f"blender binary not found: {self.binary}",
            )
            return self._finish(scene, started, None, "", failure)
        layout, out = workdir / LAYOUT_NAME, workdir / OUTPUT_NAME
        try:
            outcome = run_process(
                self.command(binary, layout, out), self.timeout_s, cwd=workdir
            )
        except OSError as exc:
            failure = PrevizRenderFailure(
                kind="binary_missing", message=f"cannot execute {binary}: {exc}"
            )
            return self._finish(scene, started, None, "", failure)
        failure = self._classify(outcome, out) or _check_passes(scene, workdir)
        return self._finish(
            scene, started, None if failure else out, _tail(outcome.output), failure
        )

    def _classify(
        self, outcome: _ProcessOutcome, out: Path
    ) -> PrevizRenderFailure | None:
        """Map a finished process + output file to a failure (None == usable MP4)."""
        if outcome.returncode is None:
            return PrevizRenderFailure(
                kind="timeout", message=f"blender exceeded {self.timeout_s:.0f}s"
            )
        if outcome.returncode != 0:
            return PrevizRenderFailure(
                kind="nonzero_exit", message=f"blender exited with {outcome.returncode}"
            )
        if not out.is_file() or out.stat().st_size == 0:
            return PrevizRenderFailure(
                kind="no_output", message=f"blender exited 0 but wrote no {out.name}"
            )
        return None

    def _finish(
        self,
        scene: PrevizScene,
        started: float,
        mp4: Path | None,
        tail: str,
        failure: PrevizRenderFailure | None,
    ) -> RenderResult:
        """Build the result and emit one semantic log line for it."""
        passes = (
            mp4.parent / PASSES_DIR if mp4 is not None and scene.render.passes else None
        )
        result = RenderResult(
            ok=failure is None,
            mp4_path=mp4,
            seconds=round(time.monotonic() - started, 3),
            blender_version=None
            if failure is not None and failure.kind in _NO_VERSION_PROBE
            else self.version(),
            stderr_tail=tail,
            failure=failure,
            pass_dir=passes,
        )
        _log_result(scene, result, self.binary)
        return result


def safe_asset_name(name: str) -> bool:
    """A plain file name (no directories, traversal, hidden files or reserved outputs)."""
    return (
        bool(name)
        and Path(name).name == name
        and not name.startswith(".")
        and name not in (LAYOUT_NAME, OUTPUT_NAME, PASSES_DIR)
    )


def prepare_workdir(
    scene: PrevizScene, workdir: Path, assets: dict[str, Path]
) -> str | None:
    """Copy assets, write layout.json, clear stale outputs; returns a reason if invalid."""
    bad = sorted(name for name in assets if not safe_asset_name(name))
    if bad:
        return f"unsafe asset names: {bad}"
    missing = sorted(name for name, src in assets.items() if not Path(src).is_file())
    if missing:
        return f"asset sources missing: {missing}"
    workdir.mkdir(parents=True, exist_ok=True)
    for name, src in assets.items():
        shutil.copyfile(src, workdir / name)
    reason = _projection_problem(scene, workdir)
    if reason is not None:
        return reason
    (workdir / LAYOUT_NAME).write_text(scene.model_dump_json(), encoding="utf-8")
    (workdir / OUTPUT_NAME).unlink(missing_ok=True)
    shutil.rmtree(workdir / PASSES_DIR, ignore_errors=True)
    return None


def _projection_problem(scene: PrevizScene, workdir: Path) -> str | None:
    """Projection image must be a relative path inside workdir that exists."""
    if scene.projection is None:
        return None
    rel = Path(scene.projection.image_file)
    if rel.is_absolute() or ".." in rel.parts:
        return f"projection.image_file must be relative to layout.json: {rel}"
    if not (workdir / rel).is_file():
        return f"projection image not found in workdir: {rel}"
    return None


def _check_passes(scene: PrevizScene, workdir: Path) -> PrevizRenderFailure | None:
    """Requested passes must have produced passes/ids.json."""
    if not scene.render.passes or (workdir / PASSES_DIR / "ids.json").is_file():
        return None
    return PrevizRenderFailure(
        kind="no_output",
        message=f"passes {scene.render.passes} requested but not written",
    )


def _log_result(scene: PrevizScene, result: RenderResult, binary: str) -> None:
    """5W1H log for a finished render attempt (WARNING on failure)."""
    level = logging.INFO if result.ok else logging.WARNING
    logger.log(
        level,
        "Previz render %s for shot %s clip %s",
        "succeeded" if result.ok else "failed",
        scene.blocking.shot_id,
        scene.blocking.clip_index,
        extra={
            "who": "storygraph.previz.render",
            "where": "BlenderRunner.render",
            "what": "previz_render",
            "when": datetime.now(timezone.utc).isoformat(),
            "why": result.failure_text or "greybox previz clip requested",
            "how": f"{binary} -b build_scene v{BUILD_SCENE_VERSION} engine={scene.render.engine}",
            "shot_id": scene.blocking.shot_id,
            "scene_id": scene.blocking.scene_id,
            "clip_index": scene.blocking.clip_index,
            "seconds": result.seconds,
            "blender_version": result.blender_version,
            "failure_kind": result.failure.kind if result.failure else None,
        },
    )
