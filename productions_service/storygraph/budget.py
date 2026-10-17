"""Deterministic Reference Budgeter (`select_references`) and Pillow composite sheet builder."""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field

from PIL import Image

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
    img_a: Image.Image, img_b: Image.Image, gutter: int = 16
) -> bytes:
    target_h = max(img_a.height, img_b.height, 256)
    w_a = max(1, int(img_a.width * (target_h / max(1, img_a.height))))
    w_b = max(1, int(img_b.width * (target_h / max(1, img_b.height))))
    canvas = Image.new("RGB", (w_a + gutter + w_b, target_h), color=(255, 255, 255))
    canvas.paste(img_a.resize((w_a, target_h)), (0, 0))
    canvas.paste(img_b.resize((w_b, target_h)), (w_a + gutter, 0))
    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue()


def build_composite_sheet(
    repo: Repo,
    asset_a: Asset,
    asset_b: Asset,
) -> Asset:
    """Stitch two character sheets side-by-side (left/right) with a 16px white gutter via Pillow."""
    pair_ids = sorted([asset_a.id, asset_b.id])
    pair_digest = hashlib.sha256(f"{pair_ids[0]}:{pair_ids[1]}".encode()).hexdigest()[
        :12
    ]
    comp_base_id = f"ast_comp_{pair_digest}"
    for ex in repo.list_assets(kind="composite_sheet"):
        if ex.id.startswith(comp_base_id) and ex.status != Status.SUPERSEDED:
            return ex
    img_a = _load_or_fallback_rgb(repo, asset_a.uri, (45, 55, 72))
    img_b = _load_or_fallback_rgb(repo, asset_b.uri, (74, 85, 104))
    png_bytes = _render_side_by_side_png(img_a, img_b)
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
            generation_prompt=f"Composite sheet of {asset_a.id} + {asset_b.id}",
            model="pillow-composite",
        )
    )


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
            )
        )
    return out


def _build_prop_candidates(
    view: ShotView, action_subjects: set[str]
) -> list[_Candidate]:
    out: list[_Candidate] = []
    for pid in view.shot.prop_ids:
        pent = view.prop_entities.get(pid)
        papp = view.prop_appearances.get(pid)
        passets = view.prop_assets.get(pid, [])
        p_asset = passets[-1] if passets else None
        is_close_focus = (
            view.shot.camera.focus_target_id == pid
            or view.shot.camera.shot_size in ("ECU", "CU")
            or pid in action_subjects
        )
        p_score = 70 if is_close_focus else 40
        p_name = pent.canonical_name if pent else pid
        p_desc = papp.visual_description if papp else ""
        out.append(
            _Candidate(
                pid, "object", p_score, p_asset, f"{p_name}: {p_desc}".strip(": ")
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
    candidates.sort(key=lambda x: (-x.score, x.entity_id))
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
        generation_prompt=f"Composite sheet of {c1.entity_id} and {c2.entity_id}",
        model="pillow-composite",
    )


def _allocate_non_loc_pool(
    remaining_pool: list[_Candidate],
    avail_for_non_loc: int,
    cfg: Config,
    repo: Repo | None,
    dropped_verbal: list[str],
) -> tuple[list[Asset], list[tuple[Asset, Asset]]]:
    high_pri = [c for c in remaining_pool if c.score >= 70]
    composites_to_build: list[tuple[Asset, Asset]] = []
    selected_assets: list[Asset] = []
    used_ids: set[str] = set()
    if len(high_pri) > avail_for_non_loc >= 1 and cfg.caps.max_composite_subjects >= 2:
        char_high = [
            c for c in high_pri if c.entity_type == "character" and c.asset is not None
        ]
        if len(char_high) >= 2:
            c1, c2 = char_high[0], char_high[1]
            assert c1.asset is not None and c2.asset is not None
            composites_to_build.append((c1.asset, c2.asset))
            comp = (
                build_composite_sheet(repo, c1.asset, c2.asset)
                if repo
                else _make_in_memory_composite(c1, c2)
            )
            selected_assets.append(comp)
            used_ids = {c1.entity_id, c2.entity_id}
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

    with_assets = [c for c in candidates if c.asset is not None]
    dropped_verbal = [c.verbal_description for c in candidates if c.asset is None]
    reserved_loc: _Candidate | None = None
    remaining_pool: list[_Candidate] = []
    for c in with_assets:
        if c.entity_type == "location" and max_slots >= 3 and reserved_loc is None:
            reserved_loc = c
        else:
            remaining_pool.append(c)

    avail = max_slots - (1 if reserved_loc else 0)
    selected, composites = _allocate_non_loc_pool(
        remaining_pool, avail, cfg, repo, dropped_verbal
    )
    if reserved_loc and reserved_loc.asset is not None:
        selected.append(reserved_loc.asset)
    return RefPlan(
        selected[:max_slots], first_frame, composites, dropped_verbal, candidate_scores
    )
