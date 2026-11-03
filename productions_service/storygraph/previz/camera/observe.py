"""ONE VLM read of a scene plate for camera calibration: room-box corners + scale priors.

Corners are in normalised image coordinates (x 0 = left .. 1 = right, y 0 = top .. 1 =
bottom); values slightly outside [0, 1] are allowed for corners just out of frame, null means
the VLM cannot place it. `mock_response` projects the default room through the default master
camera, so offline runs calibrate back to (close to) the uncalibrated camera.
"""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel

from ...schemas.previz_scene import Room
from .geometry import Frame, from_master, project_corners

OUT_OF_FRAME: Final[float] = (
    0.6  # |coord - 0.5| beyond 0.5 + this is treated as unknown
)
CORNER_FIELDS: Final[dict[str, str]] = {
    "back_top_left": "back_tl",
    "back_top_right": "back_tr",
    "back_bottom_right": "back_br",
    "back_bottom_left": "back_bl",
    "front_top_left": "front_tl",
    "front_top_right": "front_tr",
    "front_bottom_right": "front_br",
    "front_bottom_left": "front_bl",
}


class ImagePoint(BaseModel):
    x: float
    y: float


class RoomCornersObs(BaseModel):
    """Room box as the VLM sees it in the plate (see module doc for the coordinates)."""

    back_top_left: ImagePoint | None = None
    back_top_right: ImagePoint | None = None
    back_bottom_right: ImagePoint | None = None
    back_bottom_left: ImagePoint | None = None
    front_top_left: ImagePoint | None = None
    front_top_right: ImagePoint | None = None
    front_bottom_right: ImagePoint | None = None
    front_bottom_left: ImagePoint | None = None
    eye_height_m: float = (
        1.6  # clamped downstream (Gemini schemas reject exclusiveMinimum)
    )
    room_width_m: float = 8.0
    room_depth_m: float = 6.0
    room_height_m: float = 3.0

    @classmethod
    def mock_response(cls, prompt: str) -> RoomCornersObs:  # noqa: ARG003 - mock contract
        room = Room()
        frame = Frame(16, 9)
        px = project_corners(from_master(room), frame)
        names = {v: k for k, v in CORNER_FIELDS.items()}
        points = {
            names[c]: ImagePoint(x=round(u / 16, 4), y=round(v / 9, 4))
            for c, (u, v) in px.items()
        }
        return cls(
            **points,
            room_width_m=room.width,
            room_depth_m=room.depth,
            room_height_m=room.height,
        )

    def corners(self) -> dict[str, tuple[float, float]]:
        """Box-corner name (`geometry.CORNER_UNITS`) -> normalised (x, y), in-range only."""
        out: dict[str, tuple[float, float]] = {}
        for field, corner in CORNER_FIELDS.items():
            p: ImagePoint | None = getattr(self, field)
            limit = 0.5 + OUT_OF_FRAME
            if p is not None and abs(p.x - 0.5) <= limit and abs(p.y - 0.5) <= limit:
                out[corner] = (p.x, p.y)
        return out


CORNERS_PROMPT: Final[str] = (
    "The image shows the interior of a room (possibly a miniature set or an open-front box "
    "seen from outside). Model the room as a box: floor, back wall facing the camera, left "
    "and right side walls; the side of the box nearest the camera is open. Report image "
    "coordinates (x: 0 = left edge .. 1 = right edge, y: 0 = top edge .. 1 = bottom edge) "
    "of the box corners:\n"
    "- back_*: corners of the back wall (bottom = where it meets the floor, top = top of "
    "the wall / ceiling line);\n"
    "- front_*: where the side walls and the floor END nearest the camera (bottom = floor "
    "corner, top = top of the side wall); null if the walls run out of the frame.\n"
    "If furniture hides a corner, extend the visible wall/floor edges to where they meet. "
    "Corners slightly outside the frame may use values below 0 or above 1. Also estimate "
    "the camera eye height above the floor (eye_height_m) and the room's real width, "
    "depth and height in metres as if it were full size."
)
