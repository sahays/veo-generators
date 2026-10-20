"""Duplicate-beat detection and time-of-day continuity (Phase 5 story QA)."""

from __future__ import annotations

from storygraph.agents.stage_qa import stages_to_redo_for_issues
from storygraph.repo import Repo
from storygraph.schema import DialogueLine, Event, Role, Scene
from storygraph.story import detect_story_issues, find_time_regressions

_GAG = "Pip slips on the wet towel and tumbles off the kitchen chair"


def _scene(repo: Repo, idx: int, tod: str, loc: str = "loc_kitchen") -> None:
    repo.put_scene(
        Scene(
            id=f"scn_{idx:03d}",
            created_by=Role.STORY_ARCHITECT,
            index=idx,
            heading=f"INT. KITCHEN {idx}",
            location_id=loc,
            time_of_day=tod,
        )
    )


def _event(repo: Repo, eid: str, scene_idx: int, summary: str) -> None:
    repo.put_event(
        Event(
            id=eid,
            created_by=Role.STORY_ARCHITECT,
            story_order=int(eid.split("_")[1]),
            scene_id=f"scn_{scene_idx:03d}",
            summary=summary,
        )
    )


def _line(
    repo: Repo, lid: str, scene_idx: int, text: str, delivery: str = "natural"
) -> None:
    repo.put_dialogue(
        DialogueLine(
            id=lid,
            created_by=Role.SCREENWRITER,
            scene_id=f"scn_{scene_idx:03d}",
            order_in_scene=1,
            speaker_id="char_milo",
            text=text,
            delivery=delivery,
        )
    )


def _seed_repeated_story(repo: Repo) -> None:
    _scene(repo, 4, "Afternoon")
    _scene(repo, 5, "Afternoon")
    _event(repo, "evt_040", 4, _GAG)
    _event(repo, "evt_041", 4, "Milo feeds Pip a strawberry from the ceramic bowl")
    _event(
        repo, "evt_050", 5, "Pip slips on a wet towel, tumbling off the kitchen chair"
    )
    _event(repo, "evt_051", 5, "Milo opens the garden door and steps into the rain")
    _event(repo, "evt_052", 5, "Milo hands Pip the striped towel near the window")


def test_repeated_gag_across_scenes_is_flagged_on_the_repeat_only(
    tmp_repo: Repo,
) -> None:
    _seed_repeated_story(tmp_repo)
    issues = detect_story_issues(tmp_repo, "S1_EXTRACT")
    dups = [i for i in issues if i.code == "S1_DUPLICATE_EVENT"]
    assert [i.node_id for i in dups] == ["evt_050"]
    assert "evt_040" in dups[0].message


def test_distinct_beats_sharing_cast_and_props_are_not_flagged(tmp_repo: Repo) -> None:
    _scene(tmp_repo, 1, "Morning")
    _scene(tmp_repo, 2, "Morning")
    _event(tmp_repo, "evt_010", 1, "Milo waves at Pip from the kitchen window")
    _event(tmp_repo, "evt_020", 2, "Milo hands Pip the towel beside the kitchen window")
    _event(tmp_repo, "evt_021", 2, "Pip slips on the towel")  # too short to judge
    assert detect_story_issues(tmp_repo, "S1_EXTRACT") == []


def test_same_scene_steps_are_not_duplicates_but_marked_callbacks_are_exempt(
    tmp_repo: Repo,
) -> None:
    _scene(tmp_repo, 1, "Morning")
    _scene(tmp_repo, 2, "Morning")
    _event(tmp_repo, "evt_010", 1, _GAG)
    _event(tmp_repo, "evt_011", 1, _GAG.replace("kitchen", "wooden"))
    _event(tmp_repo, "evt_020", 2, f"{_GAG} (callback)")
    assert detect_story_issues(tmp_repo, "S1_EXTRACT") == []


def test_repeated_line_routes_to_screenwriter_and_events_to_architect(
    tmp_repo: Repo,
) -> None:
    _seed_repeated_story(tmp_repo)
    _line(tmp_repo, "dlg_4_1", 4, "Careful Pip, that towel is soaking wet!")
    _line(tmp_repo, "dlg_5_1", 5, "Careful, Pip! That towel is soaking wet.")
    _line(tmp_repo, "dlg_5_2", 5, "Careful Pip, that towel is soaking wet!", "callback")
    issues = detect_story_issues(tmp_repo, "S2_SCREENPLAY")
    assert [i.node_id for i in issues if i.code == "S2_DUPLICATE_LINE"] == ["dlg_5_1"]
    assert detect_story_issues(tmp_repo, "S1_EXTRACT") == [
        i for i in issues if i.code.startswith("S1_")
    ]
    assert stages_to_redo_for_issues(issues, []) == ["S1_EXTRACT", "S2_SCREENPLAY"]


def test_time_of_day_regression_only_within_continuous_scenes(tmp_repo: Repo) -> None:
    _scene(tmp_repo, 1, "Afternoon")
    _scene(tmp_repo, 2, "Morning")  # regression: same kitchen, earlier in the day
    _scene(tmp_repo, 3, "Night")
    _scene(tmp_repo, 4, "Early morning")  # next day: allowed
    _scene(tmp_repo, 5, "Dawn", loc="loc_garden")  # different place: not continuous
    regressions = find_time_regressions(tmp_repo.list_scenes())
    assert [(r.previous_scene_id, r.scene_id) for r in regressions] == [
        ("scn_001", "scn_002")
    ]
