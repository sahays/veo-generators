"""bpy camera projection: UV-project the plate from the calibrated master camera.

UVs are computed per vertex with `projmath` (exactly Blender's camera model) on subdivided
static geometry. A face shows the plate only if all its vertices are in front of the
projector, its centre lands inside the image and a ray from the projector reaches the face
centre unoccluded; otherwise it keeps its flat colour. strength in (0, 1) blends the plate
towards each flat colour (one blended image per colour); strength <= 0 disables projection.
"""

from __future__ import annotations

import os
from typing import Any

import bpy
import palette
import projmath
from mathutils import Vector

Obj = Any
NEAR_M = 0.05
ProjUV = tuple[float, float, float]
UV_MARGIN = 0.0


def load_plate(spec: dict[str, Any], layout_dir: str) -> Any | None:
    """Load the projection image (path relative to layout.json); None if unusable."""
    rel = str(spec.get("image_file", ""))
    path = os.path.normpath(os.path.join(layout_dir, rel))
    if (
        not rel
        or os.path.isabs(rel)
        or not path.startswith(os.path.normpath(layout_dir))
        or not os.path.isfile(path)
    ):
        return None
    image = bpy.data.images.load(path, check_existing=True)
    image.colorspace_settings.name = "sRGB"
    return image


def plate_material(image: Any, key: str) -> Any:
    """Material whose active image-texture node is `image` (Workbench TEXTURE colour mode)."""
    mat = bpy.data.materials.new(f"plate_{key}")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    tex = nodes.new("ShaderNodeTexImage")
    tex.image, tex.interpolation, tex.extension = image, "Linear", "EXTEND"
    bsdf = nodes.get("Principled BSDF")
    if bsdf is not None:
        mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    nodes.active = tex
    return mat


def blended_image(image: Any, color: str, strength: float) -> Any:
    """Copy of the plate lerped towards a flat colour (linear float buffer, numpy)."""
    import numpy as np

    w, h = image.size
    pixels = np.empty(w * h * 4, dtype=np.float32)
    image.pixels.foreach_get(pixels)
    flat = np.array(palette.hex_to_linear(color), dtype=np.float32)
    mixed = pixels.reshape(-1, 4) * strength + flat * (1.0 - strength)
    out = bpy.data.images.new(f"plate_{color.lstrip('#')}", w, h, float_buffer=True)
    out.colorspace_settings.name = "Linear Rec.709"
    out.pixels.foreach_set(mixed.ravel())
    return out


def face_visible(
    scene: Any, depsgraph: Any, cam: projmath.Pinhole, obj: Obj, centre: Vector
) -> bool:
    """Ray from the projector to the face centre hits this object at (about) that point."""
    origin = Vector(cam.position)
    direction = centre - origin
    dist = direction.length
    hit, loc, _n, _i, hit_obj, _m = scene.ray_cast(
        depsgraph, origin, direction.normalized(), distance=dist + 0.01
    )
    if not hit:
        return True
    return hit_obj.name == obj.name and (loc - origin).length >= dist - max(
        0.002 * dist, 0.003
    )


def visible_faces(
    scene: Any, depsgraph: Any, cam: projmath.Pinhole, obj: Obj
) -> tuple[list[ProjUV], set[int]]:
    """Read-only phase: per-vertex projector coords + indices of faces that get the plate."""
    mesh = obj.data
    mw = obj.matrix_world
    world = [mw @ v.co for v in mesh.vertices]
    proj = [projmath.project(cam, (p.x, p.y, p.z)) for p in world]
    keep = {
        poly.index
        for poly in mesh.polygons
        if _face_projected(scene, depsgraph, cam, obj, poly, world, proj)
    }
    return proj, keep


def assign_plate(obj: Obj, proj: list[ProjUV], keep: set[int], plate_mat: Any) -> None:
    """Write phase: projector UV layer + material index 1 (plate) on the kept faces."""
    mesh = obj.data
    uv_layer = mesh.uv_layers.new(name="projector")
    mesh.materials.append(plate_mat)
    for poly in mesh.polygons:
        for li in poly.loop_indices:
            u, v, _d = proj[mesh.loops[li].vertex_index]
            uv_layer.data[li].uv = (u, v)
        if poly.index in keep:
            poly.material_index = 1


def _face_projected(
    scene: Any,
    depsgraph: Any,
    cam: projmath.Pinhole,
    obj: Obj,
    poly: Any,
    world: list[Any],
    proj: list[ProjUV],
) -> bool:
    """In front of the projector, centre inside the image, and mostly unoccluded.

    Visibility samples the centre plus points halfway to each corner and keeps the face
    when at least half of them are reached unoccluded (partial occlusions stay textured).
    """
    if any(proj[i][2] <= NEAR_M for i in poly.vertices):
        return False
    corners = [world[i] for i in poly.vertices]
    centre = sum(corners, Vector()) / len(corners)
    u, v, depth = projmath.project(cam, (centre.x, centre.y, centre.z))
    if (
        not (-UV_MARGIN <= u <= 1 + UV_MARGIN and -UV_MARGIN <= v <= 1 + UV_MARGIN)
        or depth <= NEAR_M
    ):
        return False
    samples = [centre] + [centre.lerp(c, 0.5) for c in corners[:4]]
    seen = sum(1 for p in samples if face_visible(scene, depsgraph, cam, obj, p))
    return seen * 2 >= len(samples)


def apply_projection(
    spec: dict[str, Any], layout_dir: str, targets: list[tuple[Obj, str]]
) -> dict[str, Any]:
    """Project the plate onto static targets [(object, flat colour)]; returns stats for logs.

    All ray casts run before any mesh is edited: editing a mesh invalidates the evaluated
    depsgraph the ray casts use, which silently dropped hits on already-edited objects.
    """
    strength = float(spec.get("strength", 1.0))
    image = load_plate(spec, layout_dir) if strength > 0 else None
    if image is None:
        return {"projected_faces": 0, "reason": "no image or strength <= 0"}
    w, h = image.size
    cam = projmath.make_pinhole(spec.get("camera") or {}, w / max(h, 1))
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    plans = [
        (obj, flat, *visible_faces(bpy.context.scene, depsgraph, cam, obj))
        for obj, flat in targets
    ]
    mats: dict[str, Any] = {}
    for obj, flat, proj, keep in plans:
        key = "full" if strength >= 0.999 else flat
        if key not in mats:
            mats[key] = plate_material(
                image if key == "full" else blended_image(image, flat, strength),
                key.lstrip("#"),
            )
        assign_plate(obj, proj, keep, mats[key])
    return {
        "projected_faces": sum(len(p[3]) for p in plans),
        "image": f"{w}x{h}",
        "strength": strength,
    }
