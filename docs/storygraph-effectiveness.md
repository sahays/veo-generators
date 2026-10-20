# StoryGraph effectiveness: expectations and current confidence

_Status: 2026-10-20 · Context: production `p-zyt0jprz` (kids' story, robot Pip + puppy Milo, Gemini Omni 8–10s clips). To be revisited after testing more stories._

## Why this doc exists
After several pipeline iterations, the question is: is the StoryGraph helping, and what should we expect from it? This records the current assessment and the realistic targets, so the effectiveness review after more stories has a baseline.

## What the graph should do (when working)
1. **One source of truth** for who, what and where at every moment, so each clip spec is self-consistent and consistent with its neighbours.
2. **Correct references per clip:** the right character, location and object look for that moment (e.g. dry vs wet towel).
3. **Continuity by construction:** each clip's opening state equals the previous clip's closing state.
4. **Fair QA and precise repair:** the critic knows exactly what should be on screen, and the repair step knows exactly what differs.
5. **Attributable failures:** if a spec passes the graph checks and the render still fails, the cause is Omni, not us.
6. **Cheap changes:** editing a beat re-renders only the affected clips.

## Current confidence (about 6/10 overall)
| Layer | Confidence | Basis |
|---|---|---|
| Structure (entities, scenes, clip→shot, invalidation) | 8/10 | Exercised heavily; bugs fixed and tested |
| Identity (reference binding, speaker/species, `has_mouth`) | 7/10 | Visor/mouth and reference ordering fixed; per-state looks not yet rendered |
| State (events → facts → per-clip object state) | 5/10 | Was wrong until 2026-10-20; all known bugs fixed on replay, but one story only and no render yet with fully fixed specs |
| Spatial (positions, screen axis, layout) | 3/10 | Barely modelled: only left/center/right, no layout or blocking map |
| Cross-scene continuity | 5/10 | Same-location heuristic plus chaining from approved clips only; untested across scenes |

**Main risks:**
- Heuristics are tuned on a single story and may be overfit.
- Graph state comes from LLM-extracted events, and nothing checks those events against the source story.
- There is no proof yet that a correct graph raises pass rates.

## One-shot accuracy: not a realistic goal
The graph removes **our** errors (contradictory, missing or wrong instructions). It cannot remove Omni's randomness or limits: ignored shot sizes, inserted cuts, small-prop drift, identity morphing in motion, voice changes.

A film is many clips. If each clip passes first time with probability *p*, a 14-clip film passes entirely first time with probability *p*¹⁴:

| Per-clip first-try pass rate | Whole film one-shot |
|---|---|
| 60% | 0.08% |
| 80% | 4% |
| 90% | 23% |

**Realistic goal:** a high per-clip first-try pass rate, plus a small, bounded number of automatic repairs.

## Expected impact (estimates, to be confirmed with the golden set)
| Metric | Today | With working graph + prompt-doctor |
|---|---|---|
| Clip passes first try | ~15–50% (2/14 raw, 7/14 after critic calibration) | ~50–65% |
| Clip passes within 2 automatic repairs | ~60% | ~80–90% |
| Whole film without manual edits | rare | about 1–2 flagged shots per film |

**By eval dimension:**
- **Large gains (graph-driven):** object permanence, script and action adherence, clip-to-clip continuity.
- **Moderate:** character consistency (references plus per-state looks), scene consistency (location sheet plus chaining).
- **Small:** spatial consistency, unless a scene layout layer is added.
- **None (Omni limits, work around them):** camera shot size, hard cuts, voice.

**Bottom line:** a working graph should roughly halve the failures we cause and make every remaining failure explainable and repairable. Omni's limits set the ceiling.

## How we'll validate
- **Golden set:** per-dimension first-pass rates, plus attribution of each defect to spec or Omni (`docs/eval/golden_set_v1.md`).
- **More stories:** varied settings, cast and props. S1–S7 graph and lint reports reveal overfitting cheaply, before any renders.
- **Per-production graph integrity report** (planned): zero contradictions, object lifecycles complete, opening state == previous closing state.
- **Revisit:** after the new stories, compare against the baseline above and decide on a spatial layout layer.
