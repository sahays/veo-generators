"""Scene transitions: cast present in a new scene is implicitly relocated at scene entry."""

from __future__ import annotations

from storygraph.config import Config
from storygraph.repo import Repo
from storygraph.state import state_at
from storygraph.validate import validate_all
from two_location_seed import (
    GLADE,
    GUEST,
    HELPER,
    HERO,
    LANTERN,
    STREAM,
    seed_two_locations,
)


def _v3(repo: Repo, cfg: Config) -> list[str]:
    return [i.message for i in validate_all(repo, cfg) if i.code == "V3"]


def test_unnarrated_walk_relocates_cast_and_held_props_at_scene_entry(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    seed_two_locations(tmp_repo)
    first = tmp_repo.get_shot("shot_2_1")
    assert first is not None and not first.covers_event_ids  # the incident shape
    entry = 19  # post-state order just before scene 2's first Event (20)
    assert state_at(tmp_repo, HERO, entry - 1)["location"] == GLADE  # scene 1 untouched
    assert state_at(tmp_repo, HERO, entry)["location"] == STREAM
    assert state_at(tmp_repo, HELPER, entry)["location"] == STREAM
    assert state_at(tmp_repo, LANTERN, entry)["location"] == STREAM  # carried along
    assert _v3(tmp_repo, default_cfg) == []


def test_explicit_entrance_event_is_respected_not_teleported(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    seed_two_locations(tmp_repo, guest_enters=True)
    assert state_at(tmp_repo, GUEST, 19)["location"] == GLADE  # still away at entry
    assert state_at(tmp_repo, GUEST, 21)["location"] == STREAM  # the Event moves them
    entry_facts = [
        f for f in tmp_repo.list_state_facts(entity_id=GUEST)
        if f.caused_by_event_id.startswith("scene_entry:")
    ]  # fmt: skip
    assert entry_facts == []
    assert _v3(tmp_repo, default_cfg) == []


def test_cast_shown_away_from_the_shot_location_still_fails_v3(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    """The rule relocates scene cast; a shot placed at a foreign location still errors."""
    seed_two_locations(tmp_repo)
    shot = tmp_repo.get_shot("shot_2_1")
    assert shot is not None
    tmp_repo.put_shot(shot.model_copy(update={"location_id": GLADE}))
    msgs = _v3(tmp_repo, default_cfg)
    assert msgs and all("shot_2_1" in m and "opens" in m for m in msgs)
