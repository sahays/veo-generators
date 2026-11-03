"""BlenderRunner: failure classification, assets/projection validation, pass_dir contract."""

from __future__ import annotations

import json
from pathlib import Path

from previz_render_helpers import fake_blender, sample_scene
from storygraph.previz.render.runner import STDERR_TAIL_CHARS, BlenderRunner
from storygraph.schemas.previz_scene import CameraRig, PrevizScene, ProjectionSpec, Vec3

# Fake Blender that writes the MP4 (last argv) and passes/ids.json next to it.
WRITES_MP4_AND_PASSES = (
    'for a; do last="$a"; done\nprintf mp4 > "$last"\n'
    'mkdir -p "$(dirname "$last")/passes" && echo "{}" > "$(dirname "$last")/passes/ids.json"'
)


def projected(scene: PrevizScene, image_file: str) -> PrevizScene:
    rig = CameraRig(position=Vec3(y=-4.0, z=1.6), target=Vec3(y=2.0, z=1.0))
    return scene.model_copy(
        update={"projection": ProjectionSpec(image_file=image_file, camera=rig)}
    )


def test_missing_binary_is_typed_failure(tmp_path: Path) -> None:
    result = BlenderRunner(binary=str(tmp_path / "no-such-blender")).render(
        sample_scene(), tmp_path / "w"
    )
    assert (
        result.ok,
        result.mp4_path,
        result.failure.kind if result.failure else None,
    ) == (False, None, "binary_missing")
    assert result.failure_text and result.failure_text.startswith("binary_missing: ")


def test_invalid_scene_rejected_before_spawning(tmp_path: Path) -> None:
    marker = tmp_path / "spawned"
    binary = fake_blender(tmp_path, f"touch {marker}")
    result = BlenderRunner(binary=binary).render(sample_scene(width=65), tmp_path / "w")
    assert result.failure is not None and result.failure.kind == "invalid_scene"
    assert "even" in result.failure.message
    assert not marker.exists()


def test_timeout_kills_process_group_and_keeps_stderr(tmp_path: Path) -> None:
    # The child `sleep` inherits the pipe; without a process-group kill this would block 30 s.
    binary = fake_blender(tmp_path, 'echo "Fra:1 rendering" >&2\nsleep 30')
    result = BlenderRunner(binary=binary, timeout_s=1.0).render(
        sample_scene(), tmp_path / "w"
    )
    assert result.failure is not None and result.failure.kind == "timeout"
    assert "Fra:1 rendering" in result.stderr_tail
    assert result.seconds < 10


def test_nonzero_exit_keeps_only_stderr_tail(tmp_path: Path) -> None:
    binary = fake_blender(
        tmp_path,
        "head -c 5000 /dev/zero | tr '\\0' x >&2\necho 'KeyError: room' >&2\nexit 3",
    )
    result = BlenderRunner(binary=binary).render(sample_scene(), tmp_path / "w")
    assert result.failure is not None and result.failure.kind == "nonzero_exit"
    assert "3" in result.failure.message
    assert len(result.stderr_tail) == STDERR_TAIL_CHARS
    assert result.stderr_tail.rstrip().endswith("KeyError: room")


def test_exit_zero_without_file_is_no_output(tmp_path: Path) -> None:
    workdir = tmp_path / "w"
    workdir.mkdir()
    (workdir / "previz.mp4").write_bytes(b"stale from a previous run")
    result = BlenderRunner(binary=fake_blender(tmp_path, "exit 0")).render(
        sample_scene(), workdir
    )
    assert result.failure is not None and result.failure.kind == "no_output"
    assert result.mp4_path is None


def test_success_writes_layout_and_returns_last_arg_output(tmp_path: Path) -> None:
    # The fake writes to the final argv entry and checks layout.json is the one before it.
    body = 'for a; do prev="$last"; last="$a"; done\ntest -s "$prev" || exit 9\nprintf mp4 > "$last"'
    scene = sample_scene()
    result = BlenderRunner(binary=fake_blender(tmp_path, body)).render(
        scene, tmp_path / "w"
    )
    assert result.ok and result.failure is None and result.failure_text is None
    assert result.mp4_path == tmp_path / "w" / "previz.mp4"
    assert result.pass_dir is None  # no passes requested
    written = json.loads((tmp_path / "w" / "layout.json").read_text(encoding="utf-8"))
    assert PrevizScene.model_validate(written) == scene


def test_unsafe_asset_names_rejected_without_writing(tmp_path: Path) -> None:
    src = tmp_path / "plate.png"
    src.write_bytes(b"png")
    marker = tmp_path / "spawned"
    runner = BlenderRunner(binary=fake_blender(tmp_path, f"touch {marker}"))
    for name in ("../escape.png", "sub/plate.png", ".hidden", "layout.json"):
        result = runner.render(sample_scene(), tmp_path / "w", assets={name: src})
        assert result.failure is not None and result.failure.kind == "invalid_scene", (
            name
        )
    assert not marker.exists() and not (tmp_path / "escape.png").exists()


def test_projection_image_must_exist_inside_workdir(tmp_path: Path) -> None:
    runner = BlenderRunner(binary=fake_blender(tmp_path, WRITES_MP4_AND_PASSES))
    for image_file in ("plate.png", "../plate.png", "/etc/passwd"):
        result = runner.render(projected(sample_scene(), image_file), tmp_path / "w")
        assert result.failure is not None and result.failure.kind == "invalid_scene", (
            image_file
        )


def test_assets_copied_and_pass_dir_returned(tmp_path: Path) -> None:
    src = tmp_path / "src.png"
    src.write_bytes(b"plate-bytes")
    scene = projected(sample_scene(), "plate.png")
    scene.render.passes = ["object_id", "depth"]
    result = BlenderRunner(binary=fake_blender(tmp_path, WRITES_MP4_AND_PASSES)).render(
        scene, tmp_path / "w", assets={"plate.png": src}
    )
    assert result.ok, result.failure_text
    assert (tmp_path / "w" / "plate.png").read_bytes() == b"plate-bytes"
    assert result.pass_dir == tmp_path / "w" / "passes"


def test_requested_passes_missing_is_no_output(tmp_path: Path) -> None:
    scene = sample_scene()
    scene.render.passes = ["depth"]
    body = 'for a; do last="$a"; done\nprintf mp4 > "$last"'
    result = BlenderRunner(binary=fake_blender(tmp_path, body)).render(
        scene, tmp_path / "w"
    )
    assert result.failure is not None and result.failure.kind == "no_output"
    assert "passes" in result.failure.message and result.pass_dir is None
