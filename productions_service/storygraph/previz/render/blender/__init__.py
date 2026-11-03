"""Fixed bpy script modules for the previz greybox renderer (run inside Blender's Python).

Pure modules (`palette`, `parts`, `rigs`, `motion`, `projmath`) import nothing from bpy or
from each other, so they are importable and unit-testable from the service. bpy modules
(`geo`, `actors`, `projection`, `passes`, `scene_main`) are only ever executed by Blender,
which puts this directory on `sys.path` (see `../build_scene.py`) so they import siblings by
bare module name.
"""
