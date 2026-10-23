# storygraph/keyframes — graph-driven 1 fps keyframes

Independent 8–10 s Omni clips drift: outfits change, a second wooden chest appears, the
blue cabinet vanishes. This package makes the **StoryGraph drive the visual state of every
second** and lets Omni animate *between graph-correct keyframes* instead of re-imagining
the whole clip from text.

## Production: stage S8_KEYFRAMES (between S7_COMPILE and S8_RENDER)

* `stage/stage.py` `run_keyframe_stage`: scenes in parallel, clips in order. Per scene
  (`stage/scene_plans.py`): plan every clip, derive the **set pieces** (objects present in
  every clip, never held / acted on / moved: `plate/spec.py`), build or reuse (by spec hash)
  ONE locked empty-set **scene plate** (`plate/build.py`, VLM-checked: no people, every set
  piece exactly once; its layout = set-piece x centres), then re-plan the clips against that
  layout with character x carried from clip to clip. An N-second clip gets N+1 keyframes.
  **Frame 0 of clip k+1 is frame N of clip k** (same asset, `shared_from`, never
  regenerated). A current set (same plan hash, same plate, same shared start) is reused.
* Constant depth, no edit chain: every keyframe is generated from [plate, one labelled ref
  board with every present character/prop sheet (`plate/refboard.py`, no refs dropped),
  previous frame as pose-only reference] — never an edit of an edit, so nothing compounds.
* Checks: (1) deterministic **drift guard** vs the plate (`render/drift.py`, no VLM): Lab
  ΔE on 64×36 static cells (character columns masked), chroma/contrast ratios → reject and
  regenerate; (2) structured per-entity VLM check (`render/validation.py`: present / count /
  x region / own pose / outfit, short issue each). ≤2 regenerations; frames still failing are
  `manual_edit` → shot `needs_manual_edit`.
* Failures are isolated and visible: a shot (or scene) whose derivation raises gets a failed
  `KeyframeSet` (no frames, `failure_reason`), the shot is flagged, a 5W1H ERROR is logged and
  the rest continues. Transient provider errors are retried with back-off (`render/retry.py`).
  Keyframe/plate assets are written directly with content-addressed ids (no contended
  versioning transaction — the likely cause of the silently missing scenes).
* Storage: `schemas/keyframes.py` `KeyframeSet` (Firestore `keyframe_sets`, versioned like
  PromptVersion, one `active` per shot) + `Asset(kind="keyframe")` PNGs in GCS
  (`repo/keyframe_sets.py`). StageRun + 5W1H logs.
* `stage/regenerate.py`: per-frame regenerate/edit re-derives t..N as a new version, then
  re-derives the later clips of the scene; touched shots go stale. A forced stage run
  supersedes every set (server-side cascade S8_KEYFRAMES→S8_RENDER→S9→S10 via
  `services/keyframe_cascade.py`).
* S8 render reads the approved sets (`animate/sources.py` `StoredSource`). If there are no
  current keyframes it falls back to `direct` and logs a WARNING.
* Repair (`pipeline/keyframes/repair.py`): state / prop / wardrobe defects re-derive keyframes
  first, then re-render. Motion / action defects re-render only. The critic gets the clip's
  first and last keyframes as expected-state refs (`stage/ground_truth.py`).
* API: `services/keyframes_contract.py` (strip / board / regenerate). UI: keyframe strip per
  shot (`frontend/src/components/ads/storygraph/keyframes/`).

```
StoryGraph ──► plan/ (pure) ──► plate/ (scene plate) ──► render/ ──────────► animate/ (Omni)
 state_at,      KeyframePlan     set pieces, layout     plate+board(+pose)   keyframe_anchored
 clip window,   t=0..N @1fps,    1 image / scene        drift guard, VLM     | interp | animatic
 steps/events   x tracks, lint   (cached by spec hash)  check, ≤2 retries
```

## plan/ — pure, deterministic

| module | role |
|---|---|
| `models.py` | typed contracts: `PlanInput` (graph-resolved) → `KeyframePlan` (`Keyframe` per second) |
| `graph_source.py` | read-only resolver: clip window, per-beat `StateSnapshot`s (`state_at` at open, after each beat's aligned Events, at close), wardrobe from `Appearance`, identity sheets from `Asset`s |
| `permanence.py` | back-fills set pieces the State Engine only "establishes" mid-clip (the chest under the workbench) so they never pop in |
| `timing.py` | seconds per beat ∝ `duration_hint_s`; `locate(t)` by binary search; snapshot switches at the beat midpoint |
| `motion.py` | per-second character x: beat anchors (actor walks beside its target during the beat), linear in-betweens, ≤`MAX_STEP_X`/s |
| `planner.py` | `plan_keyframes(inp)`: per second → characters (wardrobe, own-action pose phrase, x, holdings), objects alive (each exactly once, holder/placement/visibility from graph), setting, camera, and the delta vs t-1 |
| `lint.py` | `lint_plan` / `lint_scene`: object set changes only with a graph change, no duplicates, ≤`MAX_STEP_X` x jump/s, wardrobe constant per scene, t=0/t=N equal clip open/close state, clean shot hand-offs |

Second 0 is the clip's opening state and the last second its closing state *by
construction*; lint re-verifies it against the input snapshots.

## render/

`KeyframeRenderer.render(inp, plan, RenderJob(plate=ScenePlate(...), shared_first=...))`:
1. each second with a non-empty delta: prompt (`prompts.frame_prompt`) enumerates every
   present character (board tile, x region, wardrobe, own pose, holdings), drawn props, fixed
   set pieces and hidden objects; images = plate, ref board, previous frame (pose only);
2. drift guard → structured VLM check → ≤`max_retries` regenerations (drifted attempts are
   never preferred); empty delta → previous image reused;
3. stored via `RepoKeyframeSink` as `Asset(kind="keyframe")`
   `ast_kf_<shot>_<plan8>_t<tt>_<sha8>`; `qa_notes` links shot, prompt version, plan hash,
   attempts, issues and drift metrics. Plates are `Asset(kind="scene_plate")`
   `ast_plate_<scene>_<spec key>` with the layout in `qa_notes`.

Image model: `ImageGenerator` (`GeminiImageGenerator`, `STORYBOARD_MODEL`, default
`gemini-nano-banana-2.1`).

## animate/

Config `video.render_strategy` (default **`direct`**, production unchanged):

| strategy | Omni request(s) |
|---|---|
| `direct` | the compiled hybrid prompt (wrapped generator untouched) |
| `keyframe_interp` | per segment `(a, b)` every `video.keyframe_stride_s` (≥3, Omni minimum): `[# Sources <FIRST_FRAME>@Image1 <LAST_FRAME>@Image2] [# References <IMAGE_REF_k>…]`, prompt = only the beats inside the segment; segments rendered in parallel, trimmed to plan and stitched |
| `animatic_edit` | 1 fps animatic MP4 (keyframe t centred on second t, duration = clip) as `[# Sources <VIDEO_0>@Video1]` + identity `IMAGE_REF_k`, short "animate… keep everything else the same" prompt |

`factory.wrap_render_strategy` is called by `Pipeline.__init__`; it returns the original
generator for `direct`.

Adapter support (`adapters/omni/inputs.py`, `fallback.py`): `Package.last_frame_uri` /
`Package.source_video_uri`; a last frame is bound only with a first frame; a source video
replaces frame bindings; the fallback ladder drops both frames together (rung 1) and keeps
the source video until the text-only rung (recorded as `source_video_dropped`).

## Experiment

`python -m storygraph.experiments.keyframe_ab --stage keyframes|render|judge|report …` —
see `docs/eval/keyframe_strategy_v1.md` for method and results.

`python -m storygraph.experiments.keyframe_plate --export-dir D --project-id P --scenes …
--before-dir B --out O` — runs the real S8 scene code on an exported production in memory
(reads refs from GCS, writes only to `O`), then writes before/after contact sheets and
`metrics.json` (manual-edit rate, drift vs scene anchor, missing entities).
