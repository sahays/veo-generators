# Work log: 2026-10-19/20, Productions (StoryGraph) hardening

Driven by production `p-zyt0jprz`, where only 3 of 15 shots passed QA but the full video was stitched anyway.

## Shipped (deployed)
| Commit | What |
|---|---|
| `b4119f8` | **Assembly gate:** S10 stitches only APPROVED clips (+ manual "stitch approved only"); fake-MP4 fallback removed. **8–10s clips:** screenwriter writes Omni-ready clips; director maps 1 clip → 1 shot and owns camera, lighting, colour grade and mood. **Omni JSON spec:** typed compact spec; hardcoded chair/towel rules and NEVER/AVOID wording removed. **Adapter:** role tags, labelled refs, first-frame binding, per-preset safety. **UI:** regenerate stage → confirm → downstream cascade; progressive-disclosure studio redesign; favicon. |
| `f5b6a09` | Species check attributes verbs to their own subject (fixed false S6 errors); validation errors show details. |
| `346d699` | **Shot repair loop:** 2 diagnosed repairs per failing shot, then "Needs your edit"; continuity followers; repair / clip-edit / regenerate API and UI. |
| `c19c742` | **Five-phase overhaul** after a full clip and graph review (8 of 9 "approved" clips were broken): per-clip state from events; object lifecycles; blocking spec linter; location sheet + approved-only first-frame chaining; per-state looks; spec-aware structured critic; spec- vs render-aware repair; duplicate-beat detection; loudness normalisation. |
| `e8ee92e` | **S7 lint remediation:** single source of limits; deterministic fixes (camera → track, split over-full clips); scoped redo with feedback. Unblocked rendering (8 → 0 blocking issues). |

Also: shot content hashing, so outdated approved clips are never reused, and render fallbacks recorded on runs.

## Key findings
- Most failures came from **our** specs, graph state and critic, not Omni. Omni's real limits are shot-size adherence, inserted hard cuts, small-prop permanence and voice consistency.
- The StoryGraph helps with structure and identity. Its state layer was wrong until today. See [storygraph-effectiveness.md](storygraph-effectiveness.md).
- Pip's voice changes per clip because Omni can't take audio references. Parked (TTS voice lock planned).

## In progress (not yet deployed)
- **Critic calibration** (done locally): a borderline score no longer blocks; out-of-frame ≠ missing; late cuts trimmed. Re-grade: 7 of 14 shots pass, up from 2.
- **Spec data fixes** (done locally): doubled names, placeholder states, consumed end states, `in_frame` visibility, camera framing policy.
- **Eval engine:** 11 dimensions (character, temporal, spatial, scene, permanence, physics, action, camera, style, audio, script adherence); the critic becomes a gate over it.
- **Prompt versioning** in the DB (lineage, patches, eval results, rollback).
- **Golden set v1:** agent-labelled, summary at `docs/eval/golden_set_v1.md` for human review.

## Next
1. **Deploy** the in-progress work and re-run `p-zyt0jprz`; measure per-dimension pass rates.
2. **Prompt-doctor:** eval feedback → typed spec patch (story locked) → re-render, keep only if improved → lessons reused across productions.
3. **Try more stories**, then revisit StoryGraph effectiveness.
4. **Later:** voice consistency, scene layout layer, eval harness / prompt optimisation.
