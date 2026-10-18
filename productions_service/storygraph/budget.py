"""Deterministic Reference Budgeter (`select_references`) and Pillow composite sheet builder."""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field

from PIL import Image, ImageDraw

from .config import Config, VideoProviderCfg
from .repo import Repo
from .schema import Asset, Role, Status
from .views import ShotView


@dataclass
class _Candidate:
    entity_id: str
    entity_type: str  # "character" | "location" | "object"
    score: int
    asset: Asset | None
    verbal_description: str
    screen_order: int = 1


@dataclass
class RefPlan:
    selected_assets: list[Asset] = field(default_factory=list)
    first_frame: Asset | None = None
    composites_to_build: list[tuple[Asset, Asset]] = field(default_factory=list)
    dropped_to_verbal: list[str] = field(default_factory=list)
    candidate_scores: dict[str, int] = field(default_factory=dict)


def _load_or_fallback_rgb(
    repo: Repo, uri: str, fallback_color: tuple[int, int, int]
) -> Image.Image:
    try:
        return Image.open(io.BytesIO(repo.blobs.get_bytes(uri))).convert("RGB")
    except Exception:
        return Image.new("RGB", (512, 512), color=fallback_color)


def _render_side_by_side_png(
    img_a: Image.Image,
    img_b: Image.Image,
    label_a: str = "LEFT",
    label_b: str = "RIGHT",
    gutter: int = 16,
) -> bytes:
    bar_h = 28
    target_h = max(img_a.height, img_b.height, 256)
    w_a = max(1, int(img_a.width * (target_h / max(1, img_a.height))))
    w_b = max(1, int(img_b.width * (target_h / max(1, img_b.height))))
    total_w = w_a + gutter + w_b
    canvas = Image.new("RGB", (total_w, target_h + bar_h), color=(255, 255, 255))
    canvas.paste(img_a.resize((w_a, target_h)), (0, bar_h))
    canvas.paste(img_b.resize((w_b, target_h)), (w_a + gutter, bar_h))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([(0, 0), (total_w, bar_h - 1)], fill=(24, 28, 36))
    mid_x = w_a + gutter // 2
    draw.line([(mid_x, 0), (mid_x, target_h + bar_h)], fill=(20, 20, 20), width=2)
    draw.text((8, 6), f"LEFT: {label_a[:28]}", fill=(255, 255, 255))
    draw.text((w_a + gutter + 8, 6), f"RIGHT: {label_b[:28]}", fill=(255, 255, 255))
    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue()


def _entity_label(repo: Repo, asset: Asset) -> str:
    if asset.depicts_entity_ids:
        ent = repo.get_entity(asset.depicts_entity_ids[0])
        if ent:
            return ent.canonical_name
        return asset.depicts_entity_ids[0]
    return asset.id


def build_composite_sheet(
    repo: Repo,
    asset_a: Asset,
    asset_b: Asset,
) -> Asset:
    """Stitch two reference sheets side-by-side (LEFT=asset_a, RIGHT=asset_b) with top header labels."""
    pair_digest = hashlib.sha256(f"{asset_a.id}:{asset_b.id}".encode()).hexdigest()[:12]
    comp_base_id = f"ast_comp_{pair_digest}"
    for ex in repo.list_assets(kind="composite_sheet"):
        if ex.id.startswith(comp_base_id) and ex.status != Status.SUPERSEDED:
            return ex
    img_a = _load_or_fallback_rgb(repo, asset_a.uri, (45, 55, 72))
    img_b = _load_or_fallback_rgb(repo, asset_b.uri, (74, 85, 104))
    label_a, label_b = _entity_label(repo, asset_a), _entity_label(repo, asset_b)
    png_bytes = _render_side_by_side_png(img_a, img_b, label_a=label_a, label_b=label_b)
    sha = hashlib.sha256(png_bytes).hexdigest()
    uri = repo.blobs.put_bytes(
        f"cache/{comp_base_id}.png", png_bytes, content_type="image/png"
    )
    depicts = list(
        dict.fromkeys(asset_a.depicts_entity_ids + asset_b.depicts_entity_ids)
    )
    return repo.add_asset(
        Asset(
            id=comp_base_id,
            created_by=Role.PIPELINE,
            status=Status.APPROVED,
            kind="composite_sheet",
            uri=uri,
            sha256=sha,
            depicts_entity_ids=depicts,
            appearance_ids=[],
            generation_prompt=f"Composite sheet LEFT={label_a} ({asset_a.id}) + RIGHT={label_b} ({asset_b.id})",
            model="pillow-composite",
        )
    )


_POS_RANK: dict[str, int] = {"left": 0, "center": 1, "right": 2, "background": 3}


def _build_cast_candidates(
    view: ShotView, speaking_ids: set[str], action_subjects: set[str]
) -> list[_Candidate]:
    out: list[_Candidate] = []
    for c in view.shot.cast:
        if c.position == "offscreen_voice":
            continue
        ent = view.cast_entities.get(c.entity_id)
        app = view.cast_appearances.get(c.entity_id)
        assets = [
            a
            for a in view.cast_assets.get(c.entity_id, [])
            if a.kind != "composite_sheet"
        ]
        c_asset = assets[-1] if assets else None
        if c.entity_id in speaking_ids or c.framing in ("ECU", "CU", "MCU"):
            c_score = 100
        elif c.entity_id in action_subjects:
            c_score = 80
        else:
            c_score = 50
        c_name = ent.canonical_name if ent else c.entity_id
        c_desc = app.visual_description if app else ""
        if app and app.wardrobe:
            c_desc = f"{c_desc} (wearing {app.wardrobe})"
        out.append(
            _Candidate(
                c.entity_id,
                "character",
                c_score,
                c_asset,
                f"{c_name}: {c_desc}".strip(": "),
                screen_order=_POS_RANK.get(c.position, 1),
            )
        )
    return out


def _build_prop_candidates(
    view: ShotView, action_subjects: set[str]
) -> list[_Candidate]:
    out: list[_Candidate] = []
    held_props = {
        st.get("holding") for st in view.cast_states.values() if st.get("holding")
    }
    for pid in view.shot.prop_ids:
        pent = view.prop_entities.get(pid)
        papp = view.prop_appearances.get(pid)
        passets = view.prop_assets.get(pid, [])
        p_asset = passets[-1] if passets else None
        is_active_or_held = (
            pid in held_props
            or view.shot.camera.focus_target_id == pid
            or view.shot.camera.shot_size in ("ECU", "CU")
            or pid in action_subjects
        )
        p_score = 85 if is_active_or_held else 45
        p_name = pent.canonical_name if pent else pid
        p_desc = papp.visual_description if papp else ""
        out.append(
            _Candidate(
                pid,
                "object",
                p_score,
                p_asset,
                f"{p_name}: {p_desc}".strip(": "),
                screen_order=4,
            )
        )
    return out


def _collect_sorted_candidates(view: ShotView) -> list[_Candidate]:
    action_subjects = {sid for b in view.shot.beats for sid in b.subject_ids}
    speaking_ids = {c.entity_id for c in view.shot.cast if c.speaking} | {
        dl.speaker_id for dl in view.dialogue_lines
    }
    loc_score = 90 if view.shot.camera.shot_size in ("WS", "EWS", "MLS") else 60
    loc_asset = view.location_assets[-1] if view.location_assets else None
    loc_verbal = (
        f"{view.location.canonical_name}: {view.location_appearance.visual_description}"
    )
    candidates = [
        _Candidate(view.location.id, "location", loc_score, loc_asset, loc_verbal),
        *_build_cast_candidates(view, speaking_ids, action_subjects),
        *_build_prop_candidates(view, action_subjects),
    ]
    candidates.sort(key=lambda x: (-x.score, x.screen_order, x.entity_id))
    return candidates


def _make_in_memory_composite(c1: _Candidate, c2: _Candidate) -> Asset:
    assert c1.asset is not None and c2.asset is not None
    return Asset(
        id=f"ast_comp_{c1.asset.id}_{c2.asset.id}_v1",
        created_by=Role.PIPELINE,
        status=Status.APPROVED,
        kind="composite_sheet",
        uri=c1.asset.uri,
        sha256=hashlib.sha256(
            f"{c1.asset.sha256}:{c2.asset.sha256}".encode()
        ).hexdigest(),
        depicts_entity_ids=[c1.entity_id, c2.entity_id],
        appearance_ids=list(
            dict.fromkeys(c1.asset.appearance_ids + c2.asset.appearance_ids)
        ),
        generation_prompt=f"Composite sheet LEFT={c1.entity_id} + RIGHT={c2.entity_id}",
        model="pillow-composite",
    )


def _allocate_non_loc_pool(
    remaining_pool: list[_Candidate],
    avail_for_non_loc: int,
    cfg: Config,
    repo: Repo | None,
    dropped_verbal: list[str],
) -> tuple[list[Asset], list[tuple[Asset, Asset]]]:
    high_pri = [c for c in remaining_pool if c.score >= 70 and c.asset is not None]
    composites_to_build: list[tuple[Asset, Asset]] = []
    selected_assets: list[Asset] = []
    used_ids: set[str] = set()
    while (
        cfg.caps.max_composite_subjects >= 2
        and (rem_high := [c for c in high_pri if c.entity_id not in used_ids])
        and len(rem_high) > (avail_for_non_loc - len(selected_assets)) >= 1
    ):
        char_high = sorted(
            [c for c in rem_high if c.entity_type == "character"],
            key=lambda x: (x.screen_order, x.entity_id),
        )
        pair_src = char_high if len(char_high) >= 2 else rem_high[:2]
        if len(pair_src) < 2:
            break
        c1, c2 = pair_src[0], pair_src[1]
        assert c1.asset is not None and c2.asset is not None
        composites_to_build.append((c1.asset, c2.asset))
        comp = (
            build_composite_sheet(repo, c1.asset, c2.asset)
            if repo
            else _make_in_memory_composite(c1, c2)
        )
        selected_assets.append(comp)
        used_ids.update((c1.entity_id, c2.entity_id))
    for c in remaining_pool:
        if c.entity_id in used_ids:
            continue
        if len(selected_assets) < avail_for_non_loc and c.asset is not None:
            selected_assets.append(c.asset)
        else:
            dropped_verbal.append(c.verbal_description)
    return selected_assets, composites_to_build


def select_references(
    view: ShotView,
    cfg: Config,
    caps: VideoProviderCfg | None = None,
    repo: Repo | None = None,
) -> RefPlan:
    """Deterministically rank candidate reference assets and fit within `caps.max_reference_images`."""
    provider_caps = caps or cfg.video
    max_slots = provider_caps.max_reference_images
    first_frame = (
        view.prev_shot_last_frame
        if (view.shot.continue_from_last_frame and provider_caps.supports_first_frame)
        else None
    )
    candidates = _collect_sorted_candidates(view)
    candidate_scores = {c.entity_id: c.score for c in candidates}
    if max_slots <= 0:
        return RefPlan(
            [],
            first_frame,
            [],
            [c.verbal_description for c in candidates],
            candidate_scores,
        )

    effective_slots = (
        max(1, max_slots - 1)
        if (first_frame is not None and max_slots >= 2)
        else max_slots
    )
    with_assets = [c for c in candidates if c.asset is not None]
    dropped_verbal = [c.verbal_description for c in candidates if c.asset is None]
    reserved_loc: _Candidate | None = None
    remaining_pool: list[_Candidate] = []
    for c in with_assets:
        if (
            c.entity_type == "location"
            and effective_slots >= 3
            and reserved_loc is None
        ):
            reserved_loc = c
        else:
            remaining_pool.append(c)

    avail = effective_slots - (1 if reserved_loc else 0)
    selected, composites = _allocate_non_loc_pool(
        remaining_pool, avail, cfg, repo, dropped_verbal
    )
    if reserved_loc and reserved_loc.asset is not None:
        selected.append(reserved_loc.asset)
    return RefPlan(
        selected[:effective_slots],
        first_frame,
        composites,
        dropped_verbal,
        candidate_scores,
    )
