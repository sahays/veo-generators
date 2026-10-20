"""Deterministic Reference Budgeter (`select_references`) and Pillow composite sheet builder."""

from __future__ import annotations

import hashlib
import io
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from PIL import Image

from .anchors.visual_states import StateRef, resolve_state_refs
from .config import Config, VideoProviderCfg
from .repair.models import RepairDirective
from .repo import Repo
from .schema import Asset, CastInShot, Role, Status
from .views import ShotView

_log = logging.getLogger(__name__)


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
    gutter: int = 8,
) -> bytes:
    _ = (label_a, label_b)
    target_h = max(img_a.height, img_b.height, 256)
    w_a = max(1, int(img_a.width * (target_h / max(1, img_a.height))))
    w_b = max(1, int(img_b.width * (target_h / max(1, img_b.height))))
    total_w = w_a + gutter + w_b
    canvas = Image.new("RGB", (total_w, target_h), color=(245, 245, 245))
    canvas.paste(img_a.resize((w_a, target_h)), (0, 0))
    canvas.paste(img_b.resize((w_b, target_h)), (w_a + gutter, 0))
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
_TYPE_RANK: dict[str, int] = {"location": 0, "character": 1, "object": 2}
_PROP_REPAIR_BOOST = 60


def _cast_score(
    c: CastInShot, speaking_ids: set[str], action_subjects: set[str]
) -> int:
    if c.entity_id in speaking_ids or c.framing in ("ECU", "CU", "MCU"):
        return 100
    return 80 if c.entity_id in action_subjects else 50


def _build_cast_candidates(
    view: ShotView,
    speaking_ids: set[str],
    action_subjects: set[str],
    state_refs: dict[str, StateRef],
) -> list[_Candidate]:
    """One identity candidate per on-screen character (state-matched sheet when available)."""
    out: list[_Candidate] = []
    for c in view.shot.cast:
        if c.position == "offscreen_voice":
            continue
        ref = state_refs.get(c.entity_id)
        ent = view.cast_entities.get(c.entity_id)
        app = ref.appearance if ref else view.cast_appearances.get(c.entity_id)
        sheets = [
            a
            for a in view.cast_assets.get(c.entity_id, [])
            if a.kind != "composite_sheet"
        ]
        c_asset = ref.asset if ref else (sheets[-1] if sheets else None)
        c_desc = app.visual_description if app else ""
        if app and app.wardrobe:
            c_desc = f"{c_desc} (wearing {app.wardrobe})"
        c_name = ent.canonical_name if ent else c.entity_id
        out.append(
            _Candidate(
                c.entity_id,
                "character",
                _cast_score(c, speaking_ids, action_subjects),
                c_asset,
                f"{c_name}: {c_desc}".strip(": "),
                screen_order=_POS_RANK.get(c.position, 1),
            )
        )
    return out


def _prop_score(view: ShotView, pid: str, action_subjects: set[str]) -> int:
    held = {st.get("holding") for st in view.cast_states.values()}
    relevant = (
        pid in held
        or view.shot.camera.focus_target_id == pid
        or view.shot.camera.shot_size in ("ECU", "CU")
        or pid in action_subjects
    )
    return 85 if relevant else 45


def _build_prop_candidates(
    view: ShotView, action_subjects: set[str], state_refs: dict[str, StateRef]
) -> list[_Candidate]:
    """One candidate per prop, scored by relevance (held / focus / action subject)."""
    out: list[_Candidate] = []
    for pid in view.shot.prop_ids:
        ref = state_refs.get(pid)
        pent = view.prop_entities.get(pid)
        papp = ref.appearance if ref else view.prop_appearances.get(pid)
        passets = view.prop_assets.get(pid, [])
        p_asset = ref.asset if ref else (passets[-1] if passets else None)
        p_name = pent.canonical_name if pent else pid
        p_desc = papp.visual_description if papp else ""
        out.append(
            _Candidate(
                pid,
                "object",
                _prop_score(view, pid, action_subjects),
                p_asset,
                f"{p_name}: {p_desc}".strip(": "),
                screen_order=4,
            )
        )
    return out


def _sort_candidates(candidates: list[_Candidate]) -> list[_Candidate]:
    """Location, then every on-screen character, then props by relevance (deterministic)."""
    return sorted(
        candidates,
        key=lambda x: (
            _TYPE_RANK[x.entity_type],
            -x.score,
            x.screen_order,
            x.entity_id,
        ),
    )


def _collect_sorted_candidates(
    view: ShotView, state_refs: dict[str, StateRef]
) -> list[_Candidate]:
    action_subjects = {sid for b in view.shot.beats for sid in b.subject_ids}
    speaking_ids = {c.entity_id for c in view.shot.cast if c.speaking} | {
        dl.speaker_id for dl in view.dialogue_lines
    }
    loc_score = 90 if view.shot.camera.shot_size in ("WS", "EWS", "MLS") else 60
    loc_asset = view.location_assets[-1] if view.location_assets else None
    loc_verbal = (
        f"{view.location.canonical_name}: {view.location_appearance.visual_description}"
    )
    return _sort_candidates(
        [
            _Candidate(view.location.id, "location", loc_score, loc_asset, loc_verbal),
            *_build_cast_candidates(view, speaking_ids, action_subjects, state_refs),
            *_build_prop_candidates(view, action_subjects, state_refs),
        ]
    )


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


@dataclass
class _Fit:
    """Slot allocation result for one candidate group."""

    assets: list[Asset] = field(default_factory=list)
    composites: list[tuple[Asset, Asset]] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)


def _fit_characters(
    chars: list[_Candidate], avail: int, can_composite: bool, repo: Repo | None
) -> _Fit:
    """Fit every on-screen character into `avail` slots, pairing sheets when over budget.

    Each LEFT/RIGHT composite (screen order) saves one slot; pairs never exceed `avail`.
    """
    overflow = len(chars) - avail
    n_pairs = min(overflow, len(chars) // 2, avail) if can_composite else 0
    if n_pairs <= 0:
        return _Fit(
            [c.asset for c in chars[:avail] if c.asset is not None],
            [],
            [c.verbal_description for c in chars[max(0, avail) :]],
        )
    by_screen = sorted(chars, key=lambda x: (x.screen_order, x.entity_id))
    pairs = [(by_screen[2 * i], by_screen[2 * i + 1]) for i in range(n_pairs)]
    paired = {c.entity_id for pair in pairs for c in pair}
    singles = [c for c in chars if c.entity_id not in paired]
    room = avail - n_pairs
    fit = _Fit(dropped=[c.verbal_description for c in singles[room:]])
    for c1, c2 in pairs:
        assert c1.asset is not None and c2.asset is not None
        fit.composites.append((c1.asset, c2.asset))
        fit.assets.append(
            build_composite_sheet(repo, c1.asset, c2.asset)
            if repo
            else _make_in_memory_composite(c1, c2)
        )
    fit.assets += [c.asset for c in singles[:room] if c.asset is not None]
    return fit


def _apply_repair_priorities(
    view: ShotView, candidates: list[_Candidate], repair: RepairDirective | None
) -> list[_Candidate]:
    """Re-rank props for a repair attempt; optionally drop the location plate.

    Characters already precede props, so `character_refs_first` needs no boost here.
    """
    if repair is None:
        return candidates
    emphasized = {n.lower() for n in repair.emphasize_objects}
    out: list[_Candidate] = []
    for c in candidates:
        drop_loc = c.entity_type == "location" and repair.refs_characters_and_props_only
        ent = view.prop_entities.get(c.entity_id)
        boost = (
            _PROP_REPAIR_BOOST
            if ent is not None and ent.canonical_name.lower() in emphasized
            else 0
        )
        out.append(
            _Candidate(
                c.entity_id,
                c.entity_type,
                c.score + boost,
                None if drop_loc else c.asset,
                c.verbal_description,
                c.screen_order,
            )
        )
    return _sort_candidates(out)


def _first_frame(
    view: ShotView, caps: VideoProviderCfg, repair: RepairDirective | None
) -> Asset | None:
    """Chained first frame from the view (already approved-only, see `anchors.chaining`)."""
    if repair is not None and repair.drop_first_frame:
        return None
    return view.prev_shot_last_frame if caps.supports_first_frame else None


def _allocate(
    candidates: list[_Candidate],
    slots: int,
    can_composite: bool,
    repo: Repo | None,
) -> _Fit:
    """Reserve the location slot, then all characters, then props by relevance."""
    with_assets = [c for c in candidates if c.asset is not None]
    fit = _Fit(dropped=[c.verbal_description for c in candidates if c.asset is None])
    loc = next((c for c in with_assets if c.entity_type == "location"), None)
    chars = [c for c in with_assets if c.entity_type == "character"]
    props = [c for c in with_assets if c.entity_type == "object"]
    reserve_loc = loc is not None and (slots >= 2 or not chars)
    avail = slots - (1 if reserve_loc else 0)
    char_fit = _fit_characters(chars, avail, can_composite, repo)
    room = max(0, avail - len(char_fit.assets))
    fit.assets = char_fit.assets + [c.asset for c in props[:room] if c.asset]
    fit.composites = char_fit.composites
    fit.dropped += char_fit.dropped + [c.verbal_description for c in props[room:]]
    if reserve_loc and loc is not None and loc.asset is not None:
        fit.assets.append(loc.asset)
    elif loc is not None:
        fit.dropped.append(loc.verbal_description)
    return fit


def _log_plan(view: ShotView, plan: RefPlan, slots: int) -> None:
    _log.info(
        "reference_plan_selected",
        extra={
            "who": "storygraph.budget",
            "where": f"select_references:{view.shot.id}",
            "what": [a.id for a in plan.selected_assets],
            "when": datetime.now(UTC).isoformat(),
            "why": f"first_frame={'yes' if plan.first_frame else 'no'}; "
            f"dropped_to_verbal={len(plan.dropped_to_verbal)}",
            "how": f"location reserved, characters, props by relevance; slots={slots}",
        },
    )


def select_references(
    view: ShotView,
    cfg: Config,
    caps: VideoProviderCfg | None = None,
    repo: Repo | None = None,
    allow_composites: bool = True,
    repair: RepairDirective | None = None,
) -> RefPlan:
    """Deterministically rank reference assets and fit within `caps.max_reference_images`.

    Slot order: the location/setting sheet is always reserved (when >= 2 slots), then every
    on-screen character's identity sheet (state-matched when the clip opens in a visual
    state; composites when over budget), then props by relevance. A chained first frame
    consumes one slot. A `repair` directive may drop the first frame / location plate,
    boost emphasized props and forbid composites.
    """
    provider_caps = caps or cfg.video
    max_slots = provider_caps.max_reference_images
    first_frame = _first_frame(view, provider_caps, repair)
    state_refs = resolve_state_refs(repo, view) if repo else {}
    candidates = _apply_repair_priorities(
        view, _collect_sorted_candidates(view, state_refs), repair
    )
    scores = {c.entity_id: c.score for c in candidates}
    if max_slots <= 0:
        return RefPlan(
            [], first_frame, [], [c.verbal_description for c in candidates], scores
        )
    slots = max_slots - 1 if (first_frame is not None and max_slots >= 2) else max_slots
    can_composite = (
        allow_composites
        and (repair is None or repair.allow_composites)
        and cfg.caps.max_composite_subjects >= 2
    )
    fit = _allocate(candidates, slots, can_composite, repo)
    plan = RefPlan(fit.assets[:slots], first_frame, fit.composites, fit.dropped, scores)
    _log_plan(view, plan, slots)
    return plan
