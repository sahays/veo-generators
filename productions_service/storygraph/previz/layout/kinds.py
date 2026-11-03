"""Object typing (pure): name/description -> parametric `PieceKind`, default size, params.

Deterministic keyword rules run first on the object's NAME, then on the description's
subject clause (the text before the first `,` `.` `;` or relation word such as "on",
"under", "next to", so "a key resting on the cabinet" never becomes a cabinet), then the
layout VLM's `kind` answer is the fallback, else a plain box. Rules are ordered most
specific first ("tool chest" before "chest", "workbench" before "bench") and each carries
its own type-default size (metres, width X / depth Y / height Z): a workbench and a
seating bench share the `bench` primitive but not the dimensions. Kind params come from
the description ("two drawers" -> drawers=2, else 3; "four shelves"; "open lid").
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final, get_args

from ...schemas.previz_scene import PieceKind

Dims = tuple[float, float, float]
_WORD = re.compile(r"[a-z]+")
_SUBJECT_END = re.compile(
    r"[,.;:(]| (?:on|under|beneath|next to|beside|near|inside|in front of|behind|"
    r"against|atop|resting|sitting|lying|holding|with a|with an) ",
)
_NUMBERS: Final[dict[str, int]] = {
    "one": 1, "single": 1, "two": 2, "pair": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}  # fmt: skip
_COUNT_RE = re.compile(  # "two drawers", "two-drawer", "3 wooden shelves"
    r"\b(\d+|" + "|".join(_NUMBERS) + r")[\s-]+(?:\w+\s+)?(drawer|shelf|shelve)s?\b"
)
_RULES: Final[tuple[tuple[tuple[str, ...], PieceKind, Dims], ...]] = (
    (("tool chest", "tool box", "toolbox", "tool case", "tool kit"), "toolbox", (0.5, 0.25, 0.25)),
    (("chest of drawers", "dresser", "drawer unit", "nightstand"), "cabinet", (0.8, 0.45, 0.85)),
    (("filing cabinet", "file cabinet"), "cabinet", (0.5, 0.6, 1.3)),
    (("wardrobe", "locker", "cupboard", "armoire", "fridge", "refrigerator"), "cabinet", (0.9, 0.6, 1.9)),
    (("cabinet", "sideboard", "drawers"), "cabinet", (0.6, 0.45, 0.8)),
    (("workbench", "work bench", "workstation", "work table", "counter"), "bench", (1.6, 0.7, 0.9)),
    (("bench", "pew"), "bench", (1.4, 0.4, 0.45)),
    (("desk", "table"), "table", (1.2, 0.7, 0.75)),
    (("bookcase", "bookshelf", "shelving", "shelf", "shelves", "rack"), "shelf", (1.0, 0.35, 1.8)),
    (("stool", "chair", "seat"), "stool", (0.4, 0.4, 0.55)),
    (("chest", "trunk", "coffer"), "chest", (0.9, 0.5, 0.5)),
    (("door", "doorway", "gate"), "door", (0.9, 0.08, 2.05)),
    (("window",), "window", (1.0, 0.08, 1.0)),
    (("barrel", "drum", "keg"), "cylinder", (0.55, 0.55, 0.85)),
    (("bucket", "pot", "vase", "jar"), "cylinder", (0.3, 0.3, 0.35)),
    (("lamp", "pole", "pillar", "column", "post"), "cylinder", (0.3, 0.3, 1.6)),
    (("bottle", "cup", "mug", "tin can", "flask", "torch", "candle"), "cylinder", (0.08, 0.08, 0.2)),
    (("crate", "box", "case", "carton", "package", "parcel"), "box", (0.45, 0.35, 0.35)),
    (("bag", "basket", "sack", "backpack"), "box", (0.35, 0.25, 0.3)),
    (("wrench", "spanner", "hammer", "screwdriver", "tool", "pliers"), "box", (0.3, 0.05, 0.05)),
    (("key", "coin", "ring", "card", "note", "letter", "phone", "photo"), "box", (0.08, 0.04, 0.02)),
)  # fmt: skip
FALLBACK: Final[Dims] = (0.25, 0.25, 0.25)
# first (most specific) rule of each kind gives its default size; reversed so it wins
DEFAULT_DIMS: Final[dict[str, Dims]] = {
    **{kind: dims for _, kind, dims in reversed(_RULES)},
    "box": FALLBACK,
}
DEFAULT_DRAWERS: Final[float] = 3.0
SHELF_PITCH: Final[float] = 0.4
_KINDS: Final[frozenset[str]] = frozenset(get_args(PieceKind))


@dataclass(frozen=True)
class Classified:
    kind: PieceKind
    dims: Dims  # type-default (width X, depth Y, height Z) in metres
    params: dict[str, float] = field(default_factory=dict)
    source: str = "default"  # name | description | vlm | default


_PATTERNS: Final[tuple[tuple[re.Pattern[str], int, int], ...]] = tuple(
    (re.compile(rf"\b{re.escape(key)}(?:e?s)?\b"), len(key), -i)
    for i, (keys, _, _) in enumerate(_RULES)
    for key in keys
)


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def match_kind(text: str) -> tuple[PieceKind, Dims] | None:
    """The rule of the keyword ending LATEST in `text` (English head noun: "Desk Lamp" is
    a lamp, "Tool Box" a toolbox); ties -> longer phrase, then earlier rule. O(rules)."""
    lowered = " ".join(_WORD.findall(text.lower()))
    best: tuple[int, int, int] | None = None
    for pattern, length, rank in _PATTERNS:
        ends = [m.end() for m in pattern.finditer(lowered)]
        if ends and (best is None or (ends[-1], length, rank) > best):
            best = (ends[-1], length, rank)
    if best is None:
        return None
    _, kind, dims = _RULES[-best[2]]
    return kind, dims


def subject_clause(description: str) -> str:
    """The description up to the first punctuation / relation word (its subject)."""
    return _SUBJECT_END.split(f" {description.lower().strip()} ", maxsplit=1)[0]


def _count(description: str, noun: str) -> int | None:
    for m in _COUNT_RE.finditer(description.lower()):
        if m.group(2).startswith(noun):
            raw = m.group(1)
            return int(raw) if raw.isdigit() else _NUMBERS[raw]
    return None


def kind_params(kind: PieceKind, description: str, height: float) -> dict[str, float]:
    """Kind-specific numbers for the Blender primitive (see `SetPiece.params`)."""
    if kind == "cabinet":
        drawers = _count(description, "drawer")
        return {"drawers": float(min(max(drawers or DEFAULT_DRAWERS, 1), 8))}
    if kind == "shelf":
        shelves = _count(description, "shel") or max(2, round(height / SHELF_PITCH))
        return {"shelves": float(min(shelves, 10))}
    if kind == "chest":
        return {"lid": 1.0, "lid_open": 1.0 if "open" in _words(description) else 0.0}
    if kind in ("bench", "table", "stool"):
        return {"leg_inset": 0.05}
    return {}


def classify(
    name: str, description: str = "", vlm_kind: str | None = None
) -> Classified:
    """Name rules > description-subject rules > VLM kind > box."""
    for source, text in (("name", name), ("description", subject_clause(description))):
        hit = match_kind(text)
        if hit is not None:
            return Classified(hit[0], hit[1], {}, source)
    if vlm_kind in _KINDS and vlm_kind != "box":
        kind: PieceKind = vlm_kind  # type: ignore[assignment]
        return Classified(kind, DEFAULT_DIMS.get(kind, FALLBACK), {}, "vlm")
    return Classified("box", FALLBACK, {}, "default")
