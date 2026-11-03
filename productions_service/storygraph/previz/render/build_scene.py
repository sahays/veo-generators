"""Fixed, versioned Blender entry script: PrevizScene JSON -> greybox MP4 (+ passes).

Usage: blender -b --factory-startup -noaudio -P build_scene.py -- layout.json out.mp4

Runs in Blender's bundled Python (stdlib + bpy only; no pydantic, no repo imports). The
implementation lives in the sibling `blender/` directory, which this script puts on
`sys.path`; importing this module from the service only exposes BUILD_SCENE_VERSION (no
bpy). World frame matches `storygraph.schemas.previz_scene` (metres, +X right, +Y depth,
+Z up); keys at time t land on frame 1 + t * fps.
"""

from __future__ import annotations

import os
import sys

BUILD_SCENE_VERSION = "2.0.0"
SCRIPT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "blender")


def main() -> None:
    """Blender entry point: expose the fixed modules and run the build + render."""
    if SCRIPT_DIR not in sys.path:
        sys.path.insert(0, SCRIPT_DIR)
    import scene_main

    scene_main.run(sys.argv, BUILD_SCENE_VERSION)


if __name__ == "__main__":
    main()
