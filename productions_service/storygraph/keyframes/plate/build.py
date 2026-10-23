"""Build a scene's locked plate and read its layout.

The plate is generated once per `PlateSpec.key` from the location sheet plus a labelled
board of the set pieces, checked by a cheap VLM (no characters, every set piece exactly once,
≤ `max_retries` regenerations) and stored by the sink keyed by scene + spec hash, so reruns
reuse the same camera and furniture layout. The layout (each set piece's horizontal centre)
is read once from the plate and drives where characters walk to (`plan.motion`).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from ...adapters.base import ImageGenerator, VLMProvider
from ..render.prompts import plate_prompt
from .refboard import compose_board
from .spec import PlateSpec

_ITEM_RE = re.compile(r"^- (.+)$")
PLATE_SEED = 101


class PieceCount(BaseModel):
    name: str
    count: int = 0


class PlateCheck(BaseModel):
    people_or_creatures: int = 0
    pieces: list[PieceCount] = Field(default_factory=list)

    @classmethod
    def mock_response(cls, prompt: str) -> PlateCheck:
        return cls(pieces=[PieceCount(name=n, count=1) for n in _listed(prompt)])


class LayoutItem(BaseModel):
    name: str
    x: float | None = Field(default=None, ge=0.0, le=1.0)


class LayoutObs(BaseModel):
    items: list[LayoutItem] = Field(default_factory=list)

    @classmethod
    def mock_response(cls, prompt: str) -> LayoutObs:
        names = _listed(prompt)
        step = 1 / (len(names) + 1)
        return cls(
            items=[
                LayoutItem(name=n, x=round((i + 1) * step, 3))
                for i, n in enumerate(names)
            ]
        )


def _listed(prompt: str) -> list[str]:
    return [
        m.group(1).strip()
        for line in prompt.splitlines()
        if (m := _ITEM_RE.match(line))
    ]


def _names_block(spec: PlateSpec) -> str:
    return "\n".join(f"- {o.name}" for o in spec.set_pieces)


def plate_issues(spec: PlateSpec, check: PlateCheck) -> list[str]:
    """Short per-piece issues: people present, a set piece missing or duplicated."""
    counts = {p.name.lower(): p.count for p in check.pieces}
    n_people = check.people_or_creatures
    out = [f"remove all {n_people} people/creatures"] if n_people else []
    for o in spec.set_pieces:
        n = counts.get(o.name.lower(), 0)
        if n != 1:
            out.append(f"{o.name}: {'missing' if n == 0 else f'appears {n} times'}")
    return out


@dataclass(frozen=True)
class PlateImage:
    png: bytes
    prompt: str
    issues: tuple[str, ...]
    layout: dict[str, float] = field(default_factory=dict)


class PlateBuilder:
    """Generate + check + locate a scene plate (image model + cheap VLM)."""

    def __init__(
        self,
        image_gen: ImageGenerator,
        vlm: VLMProvider,
        fetch: Callable[[str], bytes],
        aspect_ratio: str,
        max_retries: int = 2,
    ) -> None:
        self.image_gen, self.vlm, self.fetch = image_gen, vlm, fetch
        self.aspect_ratio, self.max_retries = aspect_ratio, max_retries

    def _inputs(self, spec: PlateSpec) -> tuple[list[bytes], list[str]]:
        loc = [self.fetch(spec.location_ref_uri)] if spec.location_ref_uri else []
        items = [(o.name, self.fetch(o.ref_uri)) for o in spec.set_pieces if o.ref_uri]
        board, labels = compose_board(items)
        return loc + ([board] if board else []), labels

    def _check(self, spec: PlateSpec, png: bytes) -> list[str]:
        ask = (
            "Count precisely. people_or_creatures = number of people or animals visible. "
            "For each furniture item report how many separate instances are visible:\n"
            + _names_block(spec)
        )
        check = self.vlm.review([png], ask, PlateCheck)
        return plate_issues(spec, check)

    def locate(self, spec: PlateSpec, png: bytes) -> dict[str, float]:
        """`set piece id -> x` read from the plate (pieces not seen are omitted)."""
        ask = (
            "For each item, report x = its horizontal centre in the image (0 = left edge, "
            "1 = right edge), null if not visible:\n" + _names_block(spec)
        )
        obs = self.vlm.review([png], ask, LayoutObs)
        by_name = {o.name.lower(): o.entity_id for o in spec.set_pieces}
        return {
            by_name[i.name.lower()]: i.x
            for i in obs.items
            if i.x is not None and i.name.lower() in by_name
        }

    def _attempt(self, text: str, images: list[bytes], attempt: int) -> bytes:
        return self.image_gen.generate(
            text, images, self.aspect_ratio, PLATE_SEED + attempt
        )

    def generate(self, spec: PlateSpec) -> PlateImage:
        """Best of ≤ `max_retries + 1` attempts (fewest issues), with its layout."""
        images, labels = self._inputs(spec)
        prompt = plate_prompt(spec, bool(spec.location_ref_uri), labels)
        best: PlateImage | None = None
        issues: list[str] = []
        for attempt in range(self.max_retries + 1):
            text = prompt + ("\nFix: " + "; ".join(issues) if issues else "")
            png = self._attempt(text, images, attempt)
            issues = self._check(spec, png)
            if best is None or len(issues) < len(best.issues):
                best = PlateImage(png, text, tuple(issues))
            if not issues:
                break
        assert best is not None  # max_retries >= 0 guarantees one attempt
        return PlateImage(
            best.png, best.prompt, best.issues, self.locate(spec, best.png)
        )
