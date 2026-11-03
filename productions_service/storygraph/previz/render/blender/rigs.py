"""Pure archetype rig tables (unit height, facing -Y): joints + coloured parts (no bpy).

Hierarchy: root (location, heading, uniform scale = height_m) > `body` (bob z, lean rot-x,
squash scale-z) > joints (rotation about local X; negative = swing forward towards -Y).
A part hangs off one node; `hand_r` is where held props attach.
"""

from __future__ import annotations

Vec = tuple[float, float, float]
Joint = tuple[str, str, Vec]  # (name, parent, pivot in parent space)
RigPart = tuple[
    str, str, str, Vec, Vec, Vec, str
]  # name, shape, node, centre, size, rot°, role
Rig = tuple[list[Joint], list[RigPart]]

NOSE_ROT: Vec = (90.0, 0.0, 0.0)  # cone tip +Z -> -Y (facing direction)
NO_ROT: Vec = (0.0, 0.0, 0.0)


def _limb_pair(
    prefix: str, x: float, y: float, z: float, parent: str = "body"
) -> list[Joint]:
    return [(f"{prefix}_l", parent, (x, y, z)), (f"{prefix}_r", parent, (-x, y, z))]


def human() -> Rig:
    """Torso, head + nose, two arms, two legs."""
    joints = [("body", "root", (0.0, 0.0, 0.0))]
    joints += _limb_pair("hip", 0.07, 0.0, 0.48) + _limb_pair(
        "shoulder", 0.17, 0.0, 0.8
    )
    joints.append(("hand_r", "shoulder_r", (0.0, 0.0, -0.36)))
    parts: list[RigPart] = [
        (
            "torso",
            "cylinder",
            "body",
            (0.0, 0.0, 0.65),
            (0.28, 0.18, 0.36),
            NO_ROT,
            "base",
        ),
        ("head", "sphere", "body", (0.0, 0.0, 0.9), (0.18, 0.18, 0.2), NO_ROT, "base"),
        (
            "nose",
            "cone",
            "body",
            (0.0, -0.1, 0.9),
            (0.05, 0.05, 0.07),
            NOSE_ROT,
            "dark",
        ),
    ]
    for side in ("l", "r"):
        parts.append(
            (
                f"leg_{side}",
                "cylinder",
                f"hip_{side}",
                (0.0, 0.0, -0.24),
                (0.1, 0.1, 0.48),
                NO_ROT,
                "base",
            )
        )
        parts.append(
            (
                f"arm_{side}",
                "cylinder",
                f"shoulder_{side}",
                (0.0, 0.0, -0.17),
                (0.06, 0.06, 0.34),
                NO_ROT,
                "base",
            )
        )
    return joints, parts


def small_robot() -> Rig:
    """Boxy body, box head with dark visor, antenna, short legs and arms."""
    joints = [("body", "root", (0.0, 0.0, 0.0))]
    joints += _limb_pair("hip", 0.12, 0.0, 0.22) + _limb_pair(
        "shoulder", 0.29, 0.0, 0.58
    )
    joints.append(("hand_r", "shoulder_r", (0.0, 0.0, -0.26)))
    parts: list[RigPart] = [
        ("chassis", "box", "body", (0.0, 0.0, 0.42), (0.5, 0.36, 0.4), NO_ROT, "base"),
        ("head", "box", "body", (0.0, 0.0, 0.75), (0.32, 0.28, 0.24), NO_ROT, "base"),
        (
            "visor",
            "box",
            "body",
            (0.0, -0.145, 0.77),
            (0.22, 0.02, 0.07),
            NO_ROT,
            "dark",
        ),
        (
            "antenna",
            "cylinder",
            "body",
            (0.0, 0.0, 0.92),
            (0.02, 0.02, 0.1),
            NO_ROT,
            "dark",
        ),
        (
            "antenna_tip",
            "sphere",
            "body",
            (0.0, 0.0, 0.975),
            (0.05, 0.05, 0.05),
            NO_ROT,
            "light",
        ),
    ]
    for side in ("l", "r"):
        parts.append(
            (
                f"leg_{side}",
                "box",
                f"hip_{side}",
                (0.0, 0.0, -0.11),
                (0.1, 0.1, 0.22),
                NO_ROT,
                "base",
            )
        )
        parts.append(
            (
                f"arm_{side}",
                "box",
                f"shoulder_{side}",
                (0.0, 0.0, -0.12),
                (0.07, 0.07, 0.24),
                NO_ROT,
                "base",
            )
        )
    return joints, parts


def quadruped() -> Rig:
    """Horizontal body along Y, head + nose at the front (-Y), 4 legs, raised tail."""
    joints = [("body", "root", (0.0, 0.0, 0.0)), ("tail", "body", (0.0, 0.4, 0.62))]
    joints += _limb_pair("hip_f", 0.1, -0.3, 0.42) + _limb_pair("hip_b", 0.1, 0.3, 0.42)
    joints = [
        (n.replace("hip_f_", "hip_f").replace("hip_b_", "hip_b"), p, v)
        for n, p, v in joints
    ]
    joints.append(("hand_r", "body", (0.0, -0.66, 0.74)))
    parts: list[RigPart] = [
        ("trunk", "box", "body", (0.0, 0.0, 0.56), (0.28, 0.8, 0.3), NO_ROT, "base"),
        ("head", "box", "body", (0.0, -0.5, 0.8), (0.22, 0.28, 0.22), NO_ROT, "base"),
        (
            "nose",
            "cone",
            "body",
            (0.0, -0.67, 0.78),
            (0.06, 0.06, 0.07),
            NOSE_ROT,
            "dark",
        ),
        (
            "tail",
            "cylinder",
            "tail",
            (0.0, 0.12, 0.07),
            (0.05, 0.05, 0.28),
            (-60.0, 0.0, 0.0),
            "base",
        ),
    ]
    for leg in ("fl", "fr", "bl", "br"):
        parts.append(
            (
                f"leg_{leg}",
                "cylinder",
                f"hip_{leg}",
                (0.0, 0.0, -0.21),
                (0.08, 0.08, 0.42),
                NO_ROT,
                "base",
            )
        )
    return joints, parts


def creature() -> Rig:
    """Blob body with two big eyes; moves by squash-and-stretch (no limbs)."""
    joints = [("body", "root", (0.0, 0.0, 0.0)), ("hand_r", "body", (-0.36, -0.2, 0.5))]
    parts: list[RigPart] = [
        ("blob", "sphere", "body", (0.0, 0.0, 0.45), (0.8, 0.7, 0.9), NO_ROT, "base"),
        (
            "eye_l",
            "sphere",
            "body",
            (0.14, -0.29, 0.66),
            (0.15, 0.15, 0.15),
            NO_ROT,
            "light",
        ),
        (
            "eye_r",
            "sphere",
            "body",
            (-0.14, -0.29, 0.66),
            (0.15, 0.15, 0.15),
            NO_ROT,
            "light",
        ),
        (
            "pupil_l",
            "sphere",
            "body",
            (0.14, -0.36, 0.66),
            (0.06, 0.06, 0.06),
            NO_ROT,
            "dark",
        ),
        (
            "pupil_r",
            "sphere",
            "body",
            (-0.14, -0.36, 0.66),
            (0.06, 0.06, 0.06),
            NO_ROT,
            "dark",
        ),
    ]
    return joints, parts


ARCHETYPES = {
    "human": human,
    "small_robot": small_robot,
    "quadruped": quadruped,
    "creature": creature,
}


def rig_for(archetype: str) -> Rig:
    """Joint + part tables for an archetype (unknown -> human)."""
    return ARCHETYPES.get(archetype, human)()
