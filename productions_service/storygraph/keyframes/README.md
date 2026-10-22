# storygraph/keyframes — graph-driven 1 fps keyframes

Independent 8–10 s Omni clips drift: outfits change, a second wooden chest appears, the
blue cabinet vanishes. This package makes the **StoryGraph drive the visual state of every
second** and lets Omni animate *between graph-correct keyframes* instead of re-imagining
the whole clip from text.

## Production: stage S8_KEYFRAMES (between S7_COMPILE and S8_RENDER)

* `stage/stage.py` `run_keyframe_stage`: scenes in parallel, clips in order. An N-second clip
  gets N+1 keyframes. **Frame 0 of clip k+1 is frame N of clip k** (same asset,
  `shared_from="<shot>@tNN"`, never regenerated); the first clip of a scene starts from the
  identity and location sheets. A current set (same plan hash, same shared start) is reused.
* Checks: a VLM check against graph state *and* the previous keyframe (`unexpected_changes`),
  with ≤2 regenerations. Frames still failing are `manual_edit` → the shot gets
  `needs_manual_edit` (render skips it until edited: the shot repair policy).
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
StoryGraph ──► plan/ (pure)  ──► render/ (image model + VLM)  ──► animate/ (Omni)
 state_at,      KeyframePlan      keyframe 0 from sheets,          direct | keyframe_interp
 clip window,   t = 0..N @1fps    t>0 = EDIT of t-1 by delta,      | animatic_edit
 steps/events   + lint            VLM check, ≤2 retries, assets
```

## plan/ — pure, deterministic

| module | role |
|---|---|
| `models.py` | typed contracts: `PlanInput` (graph-resolved) → `KeyframePlan` (`Keyframe` per second) |
| `graph_source.py` | read-only resolver: clip window, per-beat `StateSnapshot`s (`state_at` at open, after each beat's aligned Events, at close), wardrobe from `Appearance`, identity sheets from `Asset`s |
| `permanence.py` | back-fills set pieces the State Engine only "establishes" mid-clip (the chest under the workbench) so they never pop in |
| `timing.py` | seconds per beat ∝ `duration_hint_s`; `locate(t)` by binary search; snapshot switches at the beat midpoint |
| `planner.py` | `plan_keyframes(inp)`: per second → characters (wardrobe, pose phrase, position, holdings), objects alive (each exactly once, holder/placement/visibility from graph), setting, camera, and the delta vs t-1 |
| `lint.py` | `lint_plan` / `lint_scene`: object set changes only with a graph change, no duplicates, ≤1 column jump/s, wardrobe constant per scene, t=0/t=N equal clip open/close state, clean shot hand-offs |

Second 0 is the clip's opening state and the last second its closing state *by
construction*; lint re-verifies it against the input snapshots.

## render/

`KeyframeRenderer.render(inp, plan, seed_png=None)`:
1. keyframe 0 = image generation from character sheets + location plate + focus prop sheets
   + full plan text (or, for clip k+1, a re-framing **edit** of clip k's final keyframe);
2. keyframe t>0 = **image edit** of keyframe t-1 carrying only `frame.delta`
   (empty delta → previous image reused, no call);
3. every generated keyframe is checked by a cheap VLM (`validation.KeyframeCheck`: object
   counts, presence, outfit) and regenerated up to `max_retries` (2) times with the issues
   fed back; the best attempt is kept;
4. stored via `RepoKeyframeSink` as versioned `Asset(kind="keyframe")`
   `ast_kf_<shot>_t<tt>_vN`; `qa_notes` links shot id, prompt version id, plan hash, attempts
   and remaining issues. Animatics are `Asset(kind="animatic")`.

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
