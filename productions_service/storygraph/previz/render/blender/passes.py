"""bpy auxiliary passes: exact per-entity ID masks and 16-bit depth (mm) PNG sequences.

Rendered after the MP4 with a dedicated look: Workbench, FLAT light, OBJECT colours, no AA,
no shadows/cavity/outline, Raw view transform and zero dither, so every pixel is exactly an
ids.json colour (or black background). Depth comes from the Z pass through the compositor,
scaled so 1 unit of the 16-bit PNG = 1 mm (65535 = no surface / >= 65.5 m).
File index = video frame index (round(t * fps), 0-based) for t = k / pass_fps.
"""

from __future__ import annotations

import json
import os
from typing import Any

import bpy
import palette

Obj = Any
DEPTH_SCALE = 1000.0 / 65535.0


def pass_frames(
    duration: float, fps: int, pass_fps: int, frame_count: int
) -> list[int]:
    """0-based video frame indices sampled at pass_fps (always includes frame 0)."""
    step = 1.0 / max(pass_fps, 1)
    out: list[int] = []
    k = 0
    while k * step < duration + 1e-9:
        idx = round(k * step * fps)
        if idx < frame_count and (not out or idx != out[-1]):
            out.append(idx)
        k += 1
    return out


def flat_id_look(scene: Any) -> None:
    """Exact, unshaded object colours on a black background."""
    scene.render.engine = "BLENDER_WORKBENCH"
    shading = scene.display.shading
    shading.light, shading.color_type = "FLAT", "OBJECT"
    shading.show_shadows = shading.show_cavity = shading.show_object_outline = False
    shading.show_specular_highlight = False
    scene.display.render_aa = "OFF"
    scene.view_settings.view_transform = "Raw"
    scene.view_settings.look = "None"
    scene.view_settings.exposure, scene.view_settings.gamma = 0.0, 1.0
    scene.render.dither_intensity = 0.0
    scene.render.use_file_extension = True
    scene.world.color = (0.0, 0.0, 0.0)
    settings = scene.render.image_settings
    settings.file_format, settings.color_mode, settings.color_depth = "PNG", "RGB", "8"


def paint_ids(entities: dict[str, list[Obj]], out_dir: str) -> None:
    """Object colour = entity ID colour; writes ids.json {entity_id: [r, g, b]}."""
    colors = palette.id_colors(list(entities))
    for entity_id, objs in entities.items():
        r, g, b = colors[entity_id]
        for obj in objs:
            obj.color = (r / 255.0, g / 255.0, b / 255.0, 1.0)
    with open(os.path.join(out_dir, "ids.json"), "w", encoding="utf-8") as handle:
        json.dump(
            {k: list(v) for k, v in colors.items()}, handle, indent=1, sort_keys=True
        )


def depth_output(scene: Any, depth_dir: str) -> None:
    """Compositor: Render Layers Depth * (1000/65535) -> 16-bit BW PNG File Output."""
    scene.view_layers[0].use_pass_z = True
    scene.use_nodes = True
    scene.render.use_compositing = True
    tree = scene.node_tree
    tree.nodes.clear()
    layers = tree.nodes.new("CompositorNodeRLayers")
    scale = tree.nodes.new("CompositorNodeMath")
    scale.operation, scale.inputs[1].default_value = "MULTIPLY", DEPTH_SCALE
    out = tree.nodes.new("CompositorNodeOutputFile")
    out.base_path = depth_dir
    out.file_slots[0].path = "depth_"
    out.format.file_format, out.format.color_mode, out.format.color_depth = (
        "PNG",
        "BW",
        "16",
    )
    composite = tree.nodes.new("CompositorNodeComposite")
    tree.links.new(layers.outputs["Depth"], scale.inputs[0])
    tree.links.new(scale.outputs[0], out.inputs[0])
    tree.links.new(layers.outputs["Image"], composite.inputs["Image"])


def render_passes(
    scene: Any,
    entities: dict[str, list[Obj]],
    out_dir: str,
    wanted: list[str],
    frames: list[int],
) -> int:
    """Render the requested passes at the given 0-based frames; returns frames written."""
    id_dir, depth_dir = (
        os.path.join(out_dir, "object_id"),
        os.path.join(out_dir, "depth"),
    )
    os.makedirs(id_dir, exist_ok=True)
    paint_ids(entities, out_dir)
    flat_id_look(scene)
    if "depth" in wanted:
        os.makedirs(depth_dir, exist_ok=True)
        depth_output(scene, depth_dir)
    for idx in frames:
        scene.frame_set(idx + 1)
        scene.render.filepath = os.path.join(id_dir, f"{idx:04d}.png")
        bpy.ops.render.render(write_still=True)
        if "depth" in wanted:
            os.replace(
                os.path.join(depth_dir, f"depth_{idx + 1:04d}.png"),
                os.path.join(depth_dir, f"{idx:04d}.png"),
            )
    if "object_id" not in wanted:
        for idx in frames:
            os.remove(os.path.join(id_dir, f"{idx:04d}.png"))
        os.rmdir(id_dir)
    return len(frames)
