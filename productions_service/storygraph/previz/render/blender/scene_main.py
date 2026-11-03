"""bpy orchestration: PrevizScene JSON -> scene -> MP4 (+ optional passes)."""

from __future__ import annotations

import json
import math
import os
import sys
import time
from typing import Any

import actors
import bpy
import geo
import passes
import projection

Json = dict[str, Any]
Obj = Any
BACKDROP_LINEAR = (0.32, 0.32, 0.33)  # neutral mid-grey world: no black void


def log(event: str, version: str, **fields: Any) -> None:
    """Structured one-line JSON event on stderr (who/where/what/how; runner keeps the tail)."""
    record = {
        "who": "previz.build_scene",
        "where": "blender",
        "what": event,
        "how": f"build_scene v{version}",
        **fields,
    }
    sys.stderr.write(json.dumps(record) + "\n")


def reset_scene() -> Any:
    """Empty the factory scene and return it."""
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    return bpy.context.scene


def build_camera(rig: Json, frames: int) -> None:
    """Tracked rig empty (Track-To target) > camera child rolled about its view axis."""
    cam_data = bpy.data.cameras.new("shot_cam")
    cam_data.lens = float(rig.get("lens_mm", 35.0))
    cam_data.sensor_fit = "HORIZONTAL"
    cam_data.sensor_width = float(rig.get("sensor_width_mm", 36.0))
    cam_data.shift_x, cam_data.shift_y = (
        float(rig.get("shift_x", 0.0)),
        float(rig.get("shift_y", 0.0)),
    )
    cam_data.clip_start, cam_data.clip_end = 0.05, 200.0
    mount, target = geo.add_empty("shot_cam_mount"), geo.add_empty("shot_cam_target")
    cam = bpy.data.objects.new("shot_cam", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    cam.parent = mount
    cam.rotation_euler = (0.0, 0.0, math.radians(float(rig.get("roll_deg", 0.0))))
    track = mount.constraints.new("TRACK_TO")
    track.target, track.track_axis, track.up_axis = target, "TRACK_NEGATIVE_Z", "UP_Y"
    start_pos = actors.vec(rig.get("position"), (0.0, -6.0, 1.6))
    start_tgt = actors.vec(rig.get("target"), (0.0, 3.0, 1.2))
    for obj, a, b in (
        (mount, start_pos, actors.vec(rig.get("end_position"), start_pos)),
        (target, start_tgt, actors.vec(rig.get("end_target"), start_tgt)),
    ):
        obj.location = a
        obj.keyframe_insert("location", frame=1)
        obj.location = b
        obj.keyframe_insert("location", frame=max(frames, 1))
    bpy.context.scene.camera = cam


def configure_engine(scene: Any, render: Json, projected: bool) -> None:
    """Workbench look (plate scenes: unlit TEXTURE + outlines) or EEVEE/Cycles."""
    engine = str(render.get("engine", "BLENDER_WORKBENCH"))
    samples = max(int(render.get("samples", 8)), 1)
    scene.render.engine = engine
    scene.view_settings.view_transform = "Standard"
    if engine == "CYCLES":
        scene.cycles.device, scene.cycles.samples, scene.cycles.use_denoising = (
            "CPU",
            samples,
            False,
        )
    elif engine == "BLENDER_EEVEE_NEXT":
        scene.eevee.taa_render_samples = samples
    shading = scene.display.shading
    shading.light = "FLAT" if projected else "STUDIO"
    shading.color_type = "TEXTURE" if projected else "MATERIAL"
    shading.show_shadows, shading.shadow_intensity = not projected, 0.35
    shading.show_cavity = False
    shading.show_object_outline = projected
    scene.display.render_aa = "8" if samples >= 8 else ("5" if samples >= 5 else "FXAA")


def configure_output(scene: Any, render: Json, frames: int, out_path: str) -> None:
    """Resolution, fps, frame range, H.264 MP4 output and the neutral backdrop."""
    scene.render.resolution_x = int(render.get("width", 480))
    scene.render.resolution_y = int(render.get("height", 270))
    scene.render.resolution_percentage = 100
    scene.render.fps, scene.render.fps_base = int(render.get("fps", 24)), 1.0
    scene.frame_start, scene.frame_end = 1, max(frames, 1)
    scene.render.image_settings.file_format = "FFMPEG"
    ffmpeg = scene.render.ffmpeg
    ffmpeg.format, ffmpeg.codec, ffmpeg.audio_codec = "MPEG4", "H264", "NONE"
    ffmpeg.constant_rate_factor, ffmpeg.ffmpeg_preset = "HIGH", "REALTIME"
    ffmpeg.gopsize = int(render.get("fps", 24))
    scene.render.use_file_extension = False
    scene.render.filepath = out_path
    world = bpy.data.worlds.new("world")
    world.color = BACKDROP_LINEAR
    scene.world = world


def build_static(
    data: Json, layout_dir: str
) -> tuple[dict[str, list[Obj]], dict[str, Any]]:
    """Room + set pieces (+ plate projection); returns ({entity: objects}, projection stats)."""
    layout = data.get("layout") or {}
    spec = data.get("projection")
    subdivide = bool(spec) and float(spec.get("strength", 1.0)) > 0
    room = geo.build_room(layout.get("room") or {}, subdivide)
    entities: dict[str, list[Obj]] = {"room": [o for o, _ in room]}
    targets = list(room)
    for piece in layout.get("set_pieces") or []:
        built = geo.build_set_piece(piece, subdivide)
        entities[str(piece.get("entity_id"))] = [o for o, _ in built]
        targets += built
    stats = (
        projection.apply_projection(spec, layout_dir, targets)
        if subdivide
        else {"projected_faces": 0}
    )
    return entities, stats


def build(
    data: Json, out_path: str, layout_dir: str
) -> tuple[int, dict[str, list[Obj]], dict[str, Any]]:
    """Build the full scene; returns (frame count, {entity: objects}, projection stats)."""
    render, blocking = data.get("render") or {}, data.get("blocking") or {}
    fps = max(int(render.get("fps", 24)), 1)
    frames = max(int(round(float(blocking.get("duration_s", 1.0)) * fps)), 1)
    scene = reset_scene()
    entities, stats = build_static(data, layout_dir)
    props = blocking.get("props") or []
    hands: dict[str, Obj] = {}
    for track in blocking.get("characters") or []:
        hand, built = actors.build_character(track, fps, frames / fps, props)
        hands[str(track.get("entity_id"))] = hand
        entities[str(track.get("entity_id"))] = [o for o, _ in built]
    for prop in props:
        entities[str(prop.get("entity_id"))] = [
            o for o, _ in actors.build_prop(prop, hands, fps)
        ]
    build_camera(data.get("camera") or {}, frames)
    configure_engine(scene, render, stats.get("projected_faces", 0) > 0)
    configure_output(scene, render, frames, out_path)
    return frames, entities, stats


def run(argv: list[str], version: str) -> None:
    """Entry: parse args, build, render the MP4, then passes; exit 3 on any failure."""
    args = argv[argv.index("--") + 1 :] if "--" in argv else []
    if len(args) < 2:
        raise SystemExit("usage: blender -b -P build_scene.py -- layout.json out.mp4")
    layout_path, out_path = args[0], args[1]
    clock = [time.monotonic()]
    try:
        with open(layout_path, encoding="utf-8") as handle:
            data = json.load(handle)
        frames, entities, stats = build(
            data, out_path, os.path.dirname(os.path.abspath(layout_path))
        )
        log(
            "scene_built",
            version,
            frames=frames,
            out=out_path,
            why="previz render requested",
            build_s=_lap(clock),
            **stats,
        )
        bpy.ops.render.render(animation=True)
        mp4_s = _lap(clock)
        written = render_requested_passes(data, entities, frames, out_path)
    except Exception as exc:  # noqa: BLE001 - report any failure to the runner via exit code
        log(
            "render_failed",
            version,
            error=f"{type(exc).__name__}: {exc}",
            why="build or render raised",
        )
        sys.stderr.flush()
        raise SystemExit(3) from exc
    log(
        "render_done",
        version,
        frames=frames,
        pass_frames=written,
        out=out_path,
        why="previz render requested",
        mp4_s=mp4_s,
        passes_s=_lap(clock),
    )


def _lap(clock: list[float]) -> float:
    """Seconds since the previous lap (and start a new one)."""
    now = time.monotonic()
    elapsed, clock[0] = round(now - clock[0], 2), now
    return elapsed


def render_requested_passes(
    data: Json, entities: dict[str, list[Obj]], frames: int, out_path: str
) -> int:
    """passes/ next to the MP4 when render.passes is non-empty; returns pass frames written."""
    render = data.get("render") or {}
    wanted = [p for p in render.get("passes") or [] if p in ("object_id", "depth")]
    if not wanted:
        return 0
    fps = max(int(render.get("fps", 24)), 1)
    out_dir = os.path.join(os.path.dirname(os.path.abspath(out_path)), "passes")
    os.makedirs(out_dir, exist_ok=True)
    idx = passes.pass_frames(frames / fps, fps, int(render.get("pass_fps", 1)), frames)
    return passes.render_passes(bpy.context.scene, entities, out_dir, wanted, idx)
