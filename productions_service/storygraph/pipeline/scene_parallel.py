"""Scene-parallel execution shared by S8 render, S9 re-qualification and the repair loop."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

from ..schema import Shot

_T = TypeVar("_T")
MAX_SCENE_WORKERS = 4


def run_scene_groups(
    groups: Sequence[Sequence[Shot]],
    chain: Callable[[Sequence[Shot]], _T],
    parallel: bool,
) -> list[_T]:
    """Run `chain` per scene group: sequential within a scene, bounded-parallel across scenes."""
    if not parallel or len(groups) <= 1:
        return [chain(g) for g in groups]
    with ThreadPoolExecutor(max_workers=min(MAX_SCENE_WORKERS, len(groups))) as pool:
        return list(pool.map(chain, groups))


def group_by_scene(shots: list[Shot]) -> list[list[Shot]]:
    """Group story-ordered shots by scene, preserving story order within each group."""
    groups: dict[str, list[Shot]] = {}
    for shot in shots:
        groups.setdefault(shot.scene_id, []).append(shot)
    return list(groups.values())
