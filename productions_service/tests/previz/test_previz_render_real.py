"""Real headless Blender renders (skipped without blender + ffmpeg): MP4, exact passes, plate."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from previz_render_helpers import (
    HAVE_RENDER_TOOLS,
    decode,
    real_blender,
    sample_scene,
    write_png_rgb,
)
from storygraph.previz.render.runner import BlenderRunner
from storygraph.schemas.previz_scene import (
    BlockingTrack,
    CameraRig,
    LocationLayout,
    PrevizScene,
    ProjectionSpec,
    RenderSettings,
    Room,
    SetPiece,
    Vec3,
)

pytestmark = pytest.mark.skipif(not HAVE_RENDER_TOOLS, reason="needs blender + ffprobe")
W, H = 160, 90
# Camera looking at the back wall (y = 6, height = 4 m > 3.525 m top-of-frame) and floor only:
# every pixel is a projected room surface. Centre ray is horizontal, so centre depth == 10 m.
INSIDE = CameraRig(
    position=Vec3(y=-4.0, z=1.5), target=Vec3(y=6.0, z=1.5), lens_mm=50.0
)


def static_scene(
    passes: bool = False,
    projection: ProjectionSpec | None = None,
    pieces: list[SetPiece] | None = None,
) -> PrevizScene:
    return PrevizScene(
        layout=LocationLayout(
            location_id="loc",
            name="Room",
            room=Room(height=4.0),
            set_pieces=pieces or [],
        ),
        camera=INSIDE,
        blocking=BlockingTrack(
            shot_id="s", scene_id="sc", clip_index=0, duration_s=0.5
        ),
        render=RenderSettings(
            width=W,
            height=H,
            fps=4,
            pass_fps=4,
            passes=["object_id", "depth"] if passes else [],
        ),
        projection=projection,
    )


def render(
    scene: PrevizScene, workdir: Path, assets: dict[str, Path] | None = None
) -> Path:
    result = BlenderRunner(binary=real_blender(), timeout_s=120.0).render(
        scene, workdir, assets
    )
    assert result.ok, result.stderr_tail
    assert result.mp4_path is not None
    return result.mp4_path


def test_real_blender_renders_expected_frames_and_size(tmp_path: Path) -> None:
    mp4 = render(sample_scene(duration=1.0, width=64, height=36, fps=12), tmp_path)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
         "stream=codec_name,width,height,nb_read_frames", "-of", "json", str(mp4)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    stream = json.loads(probe.stdout)["streams"][0]
    assert (
        stream["codec_name"],
        stream["width"],
        stream["height"],
        int(stream["nb_read_frames"]),
    ) == ("h264", 64, 36, 12)


def test_object_id_pass_is_exact_and_depth_is_metric(tmp_path: Path) -> None:
    bench = SetPiece(
        entity_id="bench",
        name="Bench",
        kind="bench",
        position=Vec3(x=-1.5, y=3.0),
        size=Vec3(x=1.2, y=0.5, z=0.8),
    )
    render(static_scene(passes=True, pieces=[bench]), tmp_path)
    passes = tmp_path / "passes"
    ids = {
        tuple(rgb): eid
        for eid, rgb in json.loads((passes / "ids.json").read_text()).items()
    }
    pixels = decode(passes / "object_id" / "0000.png", "rgb24")
    colours = {tuple(pixels[i : i + 3]) for i in range(0, len(pixels), 3)}
    assert colours <= set(
        ids
    )  # no anti-aliased / blended pixels, no background in frame
    assert {ids[c] for c in colours} == {"room", "bench"}
    depth = decode(passes / "depth" / "0000.png", "gray16le")
    centre = int.from_bytes(
        depth[2 * ((H // 2) * W + W // 2) : 2 * ((H // 2) * W + W // 2) + 2], "little"
    )
    assert centre == pytest.approx(10000, abs=60)  # back wall 10 m away, in mm
    assert sorted(p.name for p in (passes / "depth").iterdir()) == [
        "0000.png",
        "0001.png",
    ]


def _checker(path: Path) -> bytes:
    a, b = (230, 70, 40), (40, 90, 220)
    rgb = bytes(
        c
        for y in range(H)
        for x in range(W)
        for c in (a if (x // 20 + y // 15) % 2 else b)
    )
    write_png_rgb(path, W, H, rgb)
    return rgb


def _mean_abs_diff(x: bytes, y: bytes) -> float:
    return sum(abs(p - q) for p, q in zip(x, y)) / len(x)


def test_projection_from_render_camera_reproduces_the_plate(tmp_path: Path) -> None:
    plate = _checker(tmp_path / "checker.png")
    spec = ProjectionSpec(image_file="plate.png", camera=INSIDE)
    on = decode(
        render(
            static_scene(projection=spec),
            tmp_path / "on",
            {"plate.png": tmp_path / "checker.png"},
        ),
        "rgb24",
    )
    off_spec = spec.model_copy(update={"strength": 0.0})
    off = decode(
        render(
            static_scene(projection=off_spec),
            tmp_path / "off",
            {"plate.png": tmp_path / "checker.png"},
        ),
        "rgb24",
    )
    assert (
        _mean_abs_diff(on, plate) < 12.0
    )  # H.264 + 4:2:0 chroma on hard checker edges
    assert _mean_abs_diff(off, plate) > 4 * _mean_abs_diff(on, plate)
