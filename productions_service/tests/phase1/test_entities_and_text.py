"""Phase 1: entity merge evidence, mouth traits, retry targets and the identity floor."""

from __future__ import annotations

from kitchen_seed import seed_kitchen

from storygraph.agents.role.supervisor import deduplicate_entities_fuzzy, same_entity
from storygraph.budget import RefPlan
from storygraph.clips.species import detect_traits
from storygraph.compile import compile_shot
from storygraph.config import Config
from storygraph.omni.spec import OmniClipSpec
from storygraph.qa.retry_rewrite import context_from_view, rewrite_retry_feedback
from storygraph.repo import Repo
from storygraph.schema import Entity, EntityType, QAReport, Role
from storygraph.views import shot_view


def _obj(eid: str, name: str, aliases: list[str]) -> Entity:
    return Entity(
        id=eid, created_by=Role.SCRIPT_SUPERVISOR, entity_type=EntityType.OBJECT,
        canonical_name=name, aliases=aliases,
    )  # fmt: skip


def test_alias_never_merges_distinct_objects(tmp_repo: Repo) -> None:
    """Live bug: 'Bowl of Strawberries' was an alias of 'Single Strawberry' and got merged."""
    berry = _obj("obj_single_strawberry", "Single Strawberry", ["Bowl of Strawberries"])
    bowl = _obj("obj_bowl", "Bowl of Strawberries", ["Strawberry Bowl"])
    assert not same_entity(bowl, berry, 88.0)
    for ent in (berry, bowl):
        tmp_repo.put_entity(ent)
    assert deduplicate_entities_fuzzy(tmp_repo) == []


def test_same_entity_merges_on_canonical_name_or_matching_alias() -> None:
    towel = _obj("obj_towel", "Kitchen Towel", ["Dish Towel"])
    assert same_entity(_obj("obj_towel_2", "kitchen towel", []), towel, 88.0)
    assert same_entity(_obj("obj_dish", "Dish Towel", []), towel, 88.0)


def test_mouth_requires_explicit_evidence_for_robots_and_creatures() -> None:
    robot = "A small teal robot with round orange eyes and a chest light."
    assert detect_traits([robot], {}).has_mouth is False
    assert detect_traits(["A robot with a smiling mouth."], {}).has_mouth is True
    assert (
        detect_traits(["A robot whose LED face shows a mouth."], {}).has_mouth is False
    )
    assert detect_traits(["A tall farmer in a straw hat."], {}).has_mouth is True
    assert detect_traits([robot], {"has_mouth": "true"}).has_mouth is True


def test_retry_targets_only_hold_props_held_in_this_clip(tmp_repo: Repo) -> None:
    """No 'puddle/chair stays in Pip's hands' and never '<place> is empty'."""
    seed_kitchen(tmp_repo)
    ctx = context_from_view(shot_view(tmp_repo, "shot_4_2"))
    assert all(p.handler is None for p in ctx.props)
    report = QAReport(
        passed=False,
        failure_reasons=["The water puddle vanishes and the chair is duplicated"],
        artifact_flags=["object_vanished", "duplicate_prop"],
    )
    out = rewrite_retry_feedback(report, ctx)
    assert out and not any("hands" in s or "is empty" in s for s in out)


def test_identity_survives_a_tiny_budget(tmp_repo: Repo, default_cfg: Config) -> None:
    seed_kitchen(tmp_repo)
    default_cfg.video.max_prompt_chars = 200  # forces the deepest trim level
    pkg = compile_shot(shot_view(tmp_repo, "shot_4_2"), RefPlan(), default_cfg)
    spec = OmniClipSpec.model_validate_json(pkg.spec_json)
    named = [*(spec.subjects or []), *(spec.objects or [])]
    assert named and all(e.identity for e in named)
    assert spec.look is None or spec.look.composition is None  # extras trimmed first
