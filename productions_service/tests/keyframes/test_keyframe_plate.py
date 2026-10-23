"""Scene plate: set-piece selection, reference board, plate checks, plate persistence."""

from __future__ import annotations

import io

from PIL import Image

from storygraph.keyframes.plan.models import (
    BeatSpan,
    CastInput,
    KeyframePlan,
    ObjectInput,
    PlanInput,
    StateSnapshot,
)
from storygraph.keyframes.plan.planner import plan_keyframes
from storygraph.keyframes.plate.build import (
    PieceCount,
    PlateCheck,
    PlateImage,
    plate_issues,
)
from storygraph.keyframes.plate.refboard import MAX_COLS, TILE_WIDTH, compose_board
from storygraph.keyframes.plate.spec import PlateSpec, plate_spec, set_piece_ids
from storygraph.keyframes.render.sink import RepoKeyframeSink
from storygraph.repo import Repo

_ROOM = "loc_room"
_NAMES = {
    "obj_cabinet": "Blue Cabinet",
    "obj_table": "Table",
    "obj_key": "Brass Key",
    "obj_cloth": "Green Cloth",
    "obj_lamp": "Lamp",
}


def _snap(with_lamp: bool) -> StateSnapshot:
    states: dict[str, dict[str, str]] = {
        "char_a": {"location": _ROOM, "holding": "obj_key"},
        "obj_cabinet": {"location": _ROOM, "sub_location": "against the back wall"},
        "obj_table": {"location": _ROOM},
        "obj_key": {"location": _ROOM},
        "obj_cloth": {
            "location": _ROOM,
            "supported_by": "obj_cabinet",
            "sub_location": "in the drawer",
        },
    }
    if with_lamp:
        states["obj_lamp"] = {"location": _ROOM}
    return StateSnapshot(order=1, states=states)


def _clip(idx: int, with_lamp: bool) -> PlanInput:
    snap = _snap(with_lamp)
    return PlanInput(
        project_id="p",
        scene_id="scn",
        shot_id=f"shot_{idx}",
        clip_index=idx,
        duration_s=4.0,
        location_id=_ROOM,
        location_name="Workshop",
        cast=[CastInput(entity_id="char_a", name="Ava", wardrobe="yellow")],
        objects=[ObjectInput(entity_id=k, name=v) for k, v in _NAMES.items()],
        beats=[
            BeatSpan(
                index=0,
                t_start=0.0,
                t_end=4.0,
                actor_id="char_a",
                target_id="obj_table",
                action="Ava leans on it.",
            )
        ],
        snapshots=[snap, snap.model_copy(update={"order": 2})],
    )


def _pairs() -> list[tuple[PlanInput, KeyframePlan]]:
    inputs = [_clip(1, with_lamp=True), _clip(2, with_lamp=False)]
    return [(inp, plan_keyframes(inp)) for inp in inputs]


def test_set_pieces_are_constant_unheld_visible_untargeted_in_every_clip() -> None:
    # key: held; table: beat target; cloth: hidden in drawer; lamp: missing in clip 2.
    pairs = _pairs()
    assert set_piece_ids(pairs) == ["obj_cabinet"]
    spec = plate_spec(pairs)
    assert [o.entity_id for o in spec.set_pieces] == ["obj_cabinet"]


def _png(rgb: tuple[int, int, int]) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 36), rgb).save(buf, format="PNG")
    return buf.getvalue()


def test_reference_board_keeps_every_ref_and_skips_undecodable() -> None:
    refs = [(f"ref{i}", _png((30 * i, 20, 200 - 20 * i))) for i in range(7)]
    broken = [("broken", b"not an image"), ("empty", b"")]
    board, labels = compose_board(refs[:3] + broken + refs[3:])
    assert labels == [label for label, _ in refs]  # no ref dropped, order kept
    img = Image.open(io.BytesIO(board))
    assert img.width == MAX_COLS * TILE_WIDTH
    assert compose_board(broken) == (b"", [])


def _spec(*pieces: str) -> PlateSpec:
    return PlateSpec(
        scene_id="scn",
        location_name="Workshop",
        set_pieces=[ObjectInput(entity_id=f"obj_{p.lower()}", name=p) for p in pieces],
    )


def test_plate_issues_are_per_piece() -> None:
    check = PlateCheck(
        people_or_creatures=1,
        pieces=[PieceCount(name="cabinet", count=1), PieceCount(name="Table", count=2)],
    )
    assert plate_issues(_spec("Cabinet", "Table", "Lamp"), check) == [
        "remove all 1 people/creatures",
        "Table: appears 2 times",
        "Lamp: missing",
    ]
    clean = PlateCheck(pieces=[PieceCount(name="Cabinet", count=1)])
    assert plate_issues(_spec("Cabinet"), clean) == []


def test_plate_round_trips_through_the_repo_and_is_keyed_by_spec(
    tmp_repo: Repo,
) -> None:
    sink = RepoKeyframeSink(tmp_repo)
    spec = _spec("Cabinet", "Table")
    png = _png((10, 20, 200))
    layout = {"obj_cabinet": 0.12, "obj_table": 0.6}
    saved = sink.save_plate(
        spec, PlateImage(png, "prompt", ("Table: missing",), layout), "m"
    )
    loaded = sink.load_plate(spec)
    assert loaded is not None and loaded.asset_id == saved.asset_id
    assert (loaded.png, loaded.layout, loaded.issues) == (
        png,
        layout,
        ("Table: missing",),
    )
    assert sink.load_layout(spec) == layout
    changed = _spec("Cabinet")  # different set pieces -> different plate key
    assert sink.load_plate(changed) is None and sink.load_layout(changed) == {}
