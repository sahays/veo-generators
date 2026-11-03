"""bpy geometry helpers: cached materials, unit primitives, part tables -> objects."""

from __future__ import annotations

import math
from typing import Any

import bmesh
import bpy
import palette
import parts as part_tables

Obj = Any  # bpy.types.Object
Vec = tuple[float, float, float]
PROJECTION_CELL_M = (
    0.4  # target face size on projected surfaces (perspective-correct UVs)
)
MAX_CELLS = 32
Cells = tuple[int, int, int]
NO_CELLS: Cells = (1, 1, 1)
_MATERIALS: dict[str, Any] = {}


def material(color: str) -> Any:
    """One shared material per hex colour (Workbench diffuse + Principled base colour)."""
    if color in _MATERIALS:
        return _MATERIALS[color]
    mat = bpy.data.materials.new(f"flat_{color.lstrip('#')}")
    rgba = palette.hex_to_linear(color)
    mat.diffuse_color = rgba
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = rgba
        bsdf.inputs["Roughness"].default_value = 0.8
    _MATERIALS[color] = mat
    return mat


def grid_cut(bm: Any, cells: Cells) -> None:
    """Split a unit box into cells[0] x cells[1] x cells[2] slabs with axis-aligned bisects."""
    for axis, count in enumerate(cells):
        for k in range(1, count):
            co, no = [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
            co[axis], no[axis] = -0.5 + k / count, 1.0
            bmesh.ops.bisect_plane(
                bm,
                geom=bm.verts[:] + bm.edges[:] + bm.faces[:],
                plane_co=co,
                plane_no=no,
            )


def unit_bmesh(shape: str, cells: Cells = NO_CELLS) -> Any:
    """Unit primitive: box/cylinder (1 m, centred), cone (tip +Z), sphere (d = 1)."""
    bm = bmesh.new()
    if shape == "cylinder":
        bmesh.ops.create_cone(
            bm, cap_ends=True, segments=20, radius1=0.5, radius2=0.5, depth=1.0
        )
    elif shape == "cone":
        bmesh.ops.create_cone(
            bm, cap_ends=True, segments=12, radius1=0.5, radius2=0.0, depth=1.0
        )
    elif shape == "sphere":
        bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=10, radius=0.5)
    else:
        bmesh.ops.create_cube(bm, size=1.0)
        grid_cut(bm, cells)
    return bm


def add_mesh(
    name: str,
    shape: str,
    color: str,
    parent: Obj | None = None,
    cells: Cells = NO_CELLS,
) -> Obj:
    """Coloured primitive linked to the scene (optionally parented / subdivided)."""
    mesh = bpy.data.meshes.new(name)
    bm = unit_bmesh(shape, cells)
    bm.to_mesh(mesh)
    bm.free()
    smooth = shape in ("cylinder", "sphere", "cone")
    for poly in mesh.polygons:
        poly.use_smooth = smooth
    mesh.materials.append(material(color))
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.parent = parent
    return obj


def add_empty(name: str, parent: Obj | None = None) -> Obj:
    """Invisible transform node."""
    obj = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(obj)
    obj.parent = parent
    return obj


def place(obj: Obj, loc: Vec, scale: Vec, rot: Vec = (0.0, 0.0, 0.0)) -> Obj:
    """Set local location / scale / XYZ Euler rotation (degrees)."""
    obj.location = loc
    obj.scale = scale
    obj.rotation_euler = tuple(math.radians(r) for r in rot)
    return obj


def cells_for(size: Vec, subdivide: bool) -> Cells:
    """Per-axis cell counts so projected faces stay ~PROJECTION_CELL_M wide."""
    if not subdivide:
        return NO_CELLS
    a, b, c = (min(max(math.ceil(s / PROJECTION_CELL_M), 1), MAX_CELLS) for s in size)
    return (a, b, c)


def build_parts(
    prefix: str,
    table: list[part_tables.Part],
    color: str,
    parent: Obj,
    subdivide: bool = False,
) -> list[tuple[Obj, str]]:
    """Instantiate a part table under `parent`; returns [(object, flat colour)]."""
    out: list[tuple[Obj, str]] = []
    for name, shape, centre, size, role in table:
        flat = palette.tone(color, role)
        obj = add_mesh(
            f"{prefix}_{name}",
            shape,
            flat,
            parent,
            cells_for(size, subdivide and shape == "box"),
        )
        place(obj, centre, tuple(max(s, 0.005) for s in size))  # type: ignore[arg-type]
        out.append((obj, flat))
    return out


def build_room(room: dict[str, Any], subdivide: bool) -> list[tuple[Obj, str]]:
    """Room shell + apron; returns [(object, flat colour)] (all one 'room' entity)."""
    floor_c = str(room.get("floor_color", "#b08060"))
    wall_c = str(room.get("wall_color", "#d8cfc4"))
    slabs = part_tables.room_slabs(
        float(room.get("width", 8.0)),
        float(room.get("depth", 6.0)),
        float(room.get("height", 3.0)),
    )
    out: list[tuple[Obj, str]] = []
    for name, role, centre, size, tone in slabs:
        flat = palette.tone(floor_c if role == "floor" else wall_c, tone)
        obj = add_mesh(name, "box", flat, None, cells_for(size, subdivide))
        place(obj, centre, size)
        out.append((obj, flat))
    return out


def build_set_piece(piece: dict[str, Any], subdivide: bool) -> list[tuple[Obj, str]]:
    """Parametric set piece: an empty at the footprint centre (rotated) + its parts."""
    pos = piece.get("position") or {}
    size_d = piece.get("size") or {}
    size = (
        float(size_d.get("x", 1.0)),
        float(size_d.get("y", 1.0)),
        float(size_d.get("z", 1.0)),
    )
    eid = str(piece.get("entity_id", "piece"))
    root = add_empty(f"set_{eid}")
    place(
        root,
        (float(pos.get("x", 0.0)), float(pos.get("y", 0.0)), 0.0),
        (1.0, 1.0, 1.0),
        (0.0, 0.0, float(piece.get("rotation_z_deg", 0.0))),
    )
    table = part_tables.piece_parts(
        str(piece.get("kind", "box")),
        size,
        piece.get("params") or {},
        str(piece.get("shape", "box")),
    )
    return build_parts(
        f"set_{eid}", table, str(piece.get("color", "#888888")), root, subdivide
    )
