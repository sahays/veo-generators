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


@dataclass
class RefPlan:
    selected_assets: list[Asset] = field(default_factory=list)
    first_frame: Asset | None = None
    composites_to_build: list[tuple[Asset, Asset]] = field(default_factory=list)
    dropped_to_verbal: list[str] = field(default_factory=list)
    candidate_scores: dict[str, int] = field(default_factory=dict)


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
    existing = repo.list_assets(kind="composite_sheet")
    for ex in existing:
        if ex.id.startswith(comp_base_id) and ex.status != Status.SUPERSEDED:
            return ex

    try:
        bytes_a = repo.blobs.get_bytes(asset_a.uri)
        img_a = Image.open(io.BytesIO(bytes_a)).convert("RGB")
    except Exception:
        img_a = Image.new("RGB", (512, 512), color=(45, 55, 72))

    try:
        bytes_b = repo.blobs.get_bytes(asset_b.uri)
        img_b = Image.open(io.BytesIO(bytes_b)).convert("RGB")
    except Exception:
        img_b = Image.new("RGB", (512, 512), color=(74, 85, 104))

    target_h = max(img_a.height, img_b.height, 256)
    w_a = max(1, int(img_a.width * (target_h / max(1, img_a.height))))
    w_b = max(1, int(img_b.width * (target_h / max(1, img_b.height))))
    img_a_resized = img_a.resize((w_a, target_h))
    img_b_resized = img_b.resize((w_b, target_h))

    gutter = 16
    total_w = w_a + gutter + w_b
    canvas = Image.new("RGB", (total_w, target_h), color=(255, 255, 255))
    canvas.paste(img_a_resized, (0, 0))
    canvas.paste(img_b_resized, (w_a + gutter, 0))

    draw = ImageDraw.Draw(canvas)
    label_a = (
        asset_a.depicts_entity_ids[0] if asset_a.depicts_entity_ids else asset_a.id
    )
    label_b = (
        asset_b.depicts_entity_ids[0] if asset_b.depicts_entity_ids else asset_b.id
    )
    draw.rectangle([(4, 4), (min(w_a - 4, 180), 24)], fill=(0, 0, 0))
    draw.text((8, 8), label_a[:22], fill=(255, 255, 255))
    draw.rectangle(
        [(w_a + gutter + 4, 4), (min(total_w - 4, w_a + gutter + 180), 24)],
        fill=(0, 0, 0),
    )
    draw.text((w_a + gutter + 8, 8), label_b[:22], fill=(255, 255, 255))

    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    png_bytes = buf.getvalue()
    sha = hashlib.sha256(png_bytes).hexdigest()
    uri = repo.blobs.put_bytes(
        f"cache/{comp_base_id}.png", png_bytes, content_type="image/png"
    )
    depicts = list(
        dict.fromkeys(asset_a.depicts_entity_ids + asset_b.depicts_entity_ids)
    )

    comp_asset = Asset(
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
    return repo.add_asset(comp_asset)


def select_references(
    view: ShotView,
    cfg: Config,
    caps: VideoProviderCfg | None = None,
    repo: Repo | None = None,
) -> RefPlan:
    """Deterministically rank candidate reference assets and fit within `caps.max_reference_images`."""
    provider_caps = caps or cfg.video
    max_slots = provider_caps.max_reference_images

    first_frame: Asset | None = None
    if (
        view.shot.continue_from_last_frame
        and provider_caps.supports_first_frame
        and view.prev_shot_last_frame is not None
    ):
        first_frame = view.prev_shot_last_frame

    action_subjects: set[str] = set()
    for b in view.shot.beats:
        action_subjects.update(b.subject_ids)

    speaking_ids: set[str] = {c.entity_id for c in view.shot.cast if c.speaking}
    for dl in view.dialogue_lines:
        speaking_ids.add(dl.speaker_id)

    candidates: list[_Candidate] = []

    # 1. Location plate candidate
    loc_score = 90 if view.shot.camera.shot_size in ("WS", "EWS", "MLS") else 60
    loc_asset = view.location_assets[-1] if view.location_assets else None
    loc_verbal = (
        f"{view.location.canonical_name}: {view.location_appearance.visual_description}"
    )
    candidates.append(
        _Candidate(
            entity_id=view.location.id,
            entity_type="location",
            score=loc_score,
            asset=loc_asset,
            verbal_description=loc_verbal,
        )
    )

    # 2. Cast character candidates
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
        candidates.append(
            _Candidate(
                entity_id=c.entity_id,
                entity_type="character",
                score=c_score,
                asset=c_asset,
                verbal_description=f"{c_name}: {c_desc}".strip(": "),
            )
        )

    # 3. Prop / Object candidates
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
        candidates.append(
            _Candidate(
                entity_id=pid,
                entity_type="object",
                score=p_score,
                asset=p_asset,
                verbal_description=f"{p_name}: {p_desc}".strip(": "),
            )
        )

    # Deterministic sort by (-score, entity_id)
    candidates.sort(key=lambda x: (-x.score, x.entity_id))
    candidate_scores = {c.entity_id: c.score for c in candidates}

    if max_slots <= 0:
        return RefPlan(
            selected_assets=[],
            first_frame=first_frame,
            composites_to_build=[],
            dropped_to_verbal=[c.verbal_description for c in candidates],
            candidate_scores=candidate_scores,
        )

    with_assets = [c for c in candidates if c.asset is not None]
    without_assets = [c for c in candidates if c.asset is None]
    dropped_verbal: list[str] = [c.verbal_description for c in without_assets]

    # Reserve 1 slot for location plate when max_slots >= 3 and location has an asset
    reserved_loc: _Candidate | None = None
    remaining_pool: list[_Candidate] = []
    for c in with_assets:
        if c.entity_type == "location" and max_slots >= 3 and reserved_loc is None:
            reserved_loc = c
        else:
            remaining_pool.append(c)

    avail_for_non_loc = max_slots - (1 if reserved_loc else 0)
    high_pri = [c for c in remaining_pool if c.score >= 70]
    composites_to_build: list[tuple[Asset, Asset]] = []
    selected_assets: list[Asset] = []

    if len(high_pri) > avail_for_non_loc >= 1 and cfg.caps.max_composite_subjects >= 2:
        char_high = [
            c for c in high_pri if c.entity_type == "character" and c.asset is not None
        ]
        if len(char_high) >= 2:
            c1, c2 = char_high[0], char_high[1]
            assert c1.asset is not None and c2.asset is not None
            composites_to_build.append((c1.asset, c2.asset))
            if repo is not None:
                comp_asset = build_composite_sheet(repo, c1.asset, c2.asset)
            else:
                comp_asset = Asset(
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
            selected_assets.append(comp_asset)
            used_ids = {c1.entity_id, c2.entity_id}
            for c in remaining_pool:
                if c.entity_id in used_ids:
                    continue
                if len(selected_assets) < avail_for_non_loc and c.asset is not None:
                    selected_assets.append(c.asset)
                else:
                    dropped_verbal.append(c.verbal_description)
        else:
            for c in remaining_pool:
                if len(selected_assets) < avail_for_non_loc and c.asset is not None:
                    selected_assets.append(c.asset)
                else:
                    dropped_verbal.append(c.verbal_description)
    else:
        for c in remaining_pool:
            if len(selected_assets) < avail_for_non_loc and c.asset is not None:
                selected_assets.append(c.asset)
            else:
                dropped_verbal.append(c.verbal_description)

    if reserved_loc and reserved_loc.asset is not None:
        selected_assets.append(reserved_loc.asset)

    return RefPlan(
        selected_assets=selected_assets[:max_slots],
        first_frame=first_frame,
        composites_to_build=composites_to_build,
        dropped_to_verbal=dropped_verbal,
        candidate_scores=candidate_scores,
    )
