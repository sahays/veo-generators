"""Stage S3 Visual Asset Design Studio: dedicated Character, Location & Object Designers with VLM Critic Loop."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel, Field

from ..adapters.base import ImageGenerator, VLMProvider
from ..adapters.mock import MockLLMClient
from ..config import Config
from ..repo import Repo
from ..schema import Entity, EntityType, Role
from ..tools import write_tools as wt
from ..tools.registry import ToolContext
from ..views import entity_design_view
from .critic import review_visual_asset
from .runner import RoleRunResult, run_role


class AttributeKV(BaseModel):
    key: str
    value: str


class AppearanceDraft(BaseModel):
    state_label: str = "default"
    visual_description: str
    wardrobe: str | None = None
    condition_tags: list[str] = Field(default_factory=list)


class EntityDesignOutput(BaseModel):
    attributes: list[AttributeKV] = Field(default_factory=list)
    appearances: list[AppearanceDraft] = Field(default_factory=list)


def _designer_role_for_entity(entity_type: EntityType) -> tuple[Role, str]:
    if entity_type == EntityType.CHARACTER:
        return Role.CHARACTER_DESIGNER, "character_sheet"
    if entity_type == EntityType.LOCATION:
        return Role.LOCATION_DESIGNER, "location_plate"
    return Role.OBJECT_DESIGNER, "prop_sheet"


def _default_design_for_entity(
    ent: Entity, required_labels: list[str]
) -> EntityDesignOutput:
    existing_desc = ", ".join(f"{k}: {v.value}" for k, v in ent.attributes.items())
    if ent.entity_type == EntityType.CHARACTER:
        attrs = [
            AttributeKV(key="role", value="story character"),
            AttributeKV(
                key="distinctive_features", value=existing_desc or ent.canonical_name
            ),
        ]
        apps = []
        for lbl in required_labels:
            wardrobe_desc = (
                "signature character attire matching the story setting"
                if lbl == "default"
                else f"{lbl.replace('_', ' ')} attire"
            )
            apps.append(
                AppearanceDraft(
                    state_label=lbl,
                    visual_description=(
                        f"{ent.canonical_name} ({existing_desc or 'expressive protagonist with distinctive silhouette and costume'})"
                    ),
                    wardrobe=wardrobe_desc,
                    condition_tags=[lbl],
                )
            )
        return EntityDesignOutput(attributes=attrs, appearances=apps)

    if ent.entity_type == EntityType.LOCATION:
        attrs = [
            AttributeKV(key="architecture", value=existing_desc or ent.canonical_name),
            AttributeKV(key="atmosphere", value="cinematic depth and lighting"),
        ]
        apps = [
            AppearanceDraft(
                state_label=lbl,
                visual_description=(
                    f"{ent.canonical_name} ({existing_desc or 'detailed environment establishing plate matching the story world'})"
                ),
                wardrobe=None,
                condition_tags=[lbl],
            )
            for lbl in required_labels
        ]
        return EntityDesignOutput(attributes=attrs, appearances=apps)

    attrs = [
        AttributeKV(key="material", value=existing_desc or ent.canonical_name),
        AttributeKV(key="scale", value="key story prop"),
    ]
    apps = [
        AppearanceDraft(
            state_label=lbl,
            visual_description=(
                f"{ent.canonical_name} ({existing_desc or 'distinctive story object prop sheet'})"
            ),
            wardrobe=None,
            condition_tags=[lbl],
        )
        for lbl in required_labels
    ]
    return EntityDesignOutput(attributes=attrs, appearances=apps)


def design_single_entity(
    repo: Repo,
    cfg: Config,
    entity_id: str,
    image_gen: ImageGenerator,
    vlm: VLMProvider,
    mock_llm: MockLLMClient | None = None,
    force_regenerate: bool = False,
) -> tuple[list[str], int, int]:
    """Run the dedicated Designer (`CHARACTER_DESIGNER` / `LOCATION_DESIGNER` / `OBJECT_DESIGNER`) + VLM Critic loop."""
    ed_view = entity_design_view(repo, entity_id)
    ent = ed_view.entity
    role, asset_kind = _designer_role_for_entity(ent.entity_type)
    designer_ctx = ToolContext(repo=repo, role=role, cfg=cfg, image_gen=image_gen)
    critic_ctx = ToolContext(repo=repo, role=Role.CRITIC, cfg=cfg, image_gen=image_gen)
    story_context = repo.get_source_text() or ""

    res: RoleRunResult = run_role(
        role=role,
        ctx=designer_ctx,
        user_prompt=(
            f"Story context:\n{story_context}\n\n"
            f"Design {ent.entity_type} '{ent.canonical_name}' (id='{ent.id}') for required state labels "
            f"{ed_view.required_state_labels}. Make the visual_description and wardrobe 100% faithful "
            f"to this specific character/location/object in the story and the StyleGuide:\n"
            f"{ed_view.model_dump_json()}"
        ),
        output_schema=EntityDesignOutput,
        mock_llm=mock_llm,
        fallback_builder=lambda: _default_design_for_entity(
            ent, ed_view.required_state_labels
        ),
    )
    design_out: EntityDesignOutput = res.output

    safe_attrs = {
        kv.key: kv.value
        for kv in design_out.attributes
        if kv.key
        and (
            kv.key not in ent.attributes
            or ent.attributes[kv.key].provenance.value != "from_text"
        )
    }
    if safe_attrs:
        wt.set_entity_attributes(
            designer_ctx,
            entity_id=ent.id,
            attributes=safe_attrs,
            provenance="invented",
        )

    created_app_ids: list[str] = []
    max_iters = max(1, cfg.caps.design_loop_max)

    # Ensure every required state_label is covered
    draft_by_label = {a.state_label: a for a in design_out.appearances}
    for req_lbl in ed_view.required_state_labels:
        if req_lbl not in draft_by_label:
            fallback_d = _default_design_for_entity(ent, [req_lbl]).appearances[0]
            draft_by_label[req_lbl] = fallback_d

    for lbl, app_draft in draft_by_label.items():
        existing_apps = [
            a
            for a in repo.list_appearances(entity_id=ent.id, active_only=True)
            if a.state_label == lbl
        ]
        if existing_apps and existing_apps[-1].asset_ids and not force_regenerate:
            created_app_ids.append(existing_apps[-1].id)
            continue

        current_desc = app_draft.visual_description
        saved_app_dict = wt.add_appearance(
            designer_ctx,
            entity_id=ent.id,
            state_label=lbl,
            visual_description=current_desc,
            wardrobe=app_draft.wardrobe,
            condition_tags=app_draft.condition_tags,
        )
        app_id = saved_app_dict["id"]
        created_app_ids.append(app_id)

        # LoopAgent pattern: Designer generates image -> CRITIC reviews via VLM -> refine up to design_loop_max
        for iteration in range(max_iters):
            seed = 100 + iteration * 17
            asset_dict = wt._generate_entity_asset_with_adapter(
                designer_ctx,
                entity_id=ent.id,
                appearance_id=app_id,
                kind=asset_kind,
                extra_prompt=f"iteration={iteration + 1}",
                seed=seed,
            )
            asset_id = asset_dict["id"]
            critique = review_visual_asset(
                critic_ctx,
                vlm=vlm,
                asset_id=asset_id,
                appearance_id=app_id,
            )
            if critique.approved or iteration + 1 >= max_iters:
                break
            if critique.refined_visual_description:
                current_desc = critique.refined_visual_description

    return created_app_ids, res.tokens_in, res.tokens_out


def run_visual_design_studio(
    repo: Repo,
    cfg: Config,
    image_gen: ImageGenerator,
    vlm: VLMProvider,
    mock_llm: MockLLMClient | None = None,
    force_regenerate: bool = False,
) -> tuple[list[str], int, int]:
    """Fan out CHARACTER_DESIGNER, LOCATION_DESIGNER, and OBJECT_DESIGNER across all entities in parallel."""
    entities = repo.list_entities()
    if not entities:
        return [], 0, 0

    all_app_ids: list[str] = []
    total_in = 0
    total_out = 0

    with ThreadPoolExecutor(max_workers=min(4, len(entities))) as pool:
        futures = [
            pool.submit(
                design_single_entity,
                repo,
                cfg,
                ent.id,
                image_gen,
                vlm,
                mock_llm,
                force_regenerate,
            )
            for ent in entities
        ]
        for fut in futures:
            app_ids, tin, tout = fut.result()
            all_app_ids.extend(app_ids)
            total_in += tin
            total_out += tout

    return all_app_ids, total_in, total_out
