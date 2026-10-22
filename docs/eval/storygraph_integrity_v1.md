# StoryGraph integrity v1 — cross-story generalization (5 productions)

Productions: `p-og5klsx9` (fantasy forest), `p-pzbfjudf` (apartment mystery),
`p-a78w16oy` (Hindi Ramayana, vanaras), `p-0irbygdv` (workshop diagnostic),
`p-zyt0jprz` (kitchen — the story most rules were tuned on). Exports were replayed
locally (MemoryStore, mock video adapter, no LLM) through S6 + S7.

## S6 + S7 replay (before = deployed `ba8fb81`, after = this change)

| Production | S6 before | S7 before | S6 after | S7 after |
|---|---|---|---|---|
| p-og5klsx9 | FAIL V3×2 (scene 4 relocation) | FAIL 6 lint errors | PASS | PASS (6 lint demoted to shot warnings) |
| p-pzbfjudf | FAIL V3×3 (scene 4 relocation) | FAIL 1 lint error | PASS | PASS (1 demoted) |
| p-a78w16oy | FAIL species×4 ("bark" = tree bark) | FAIL 3 lint errors | PASS | PASS (3 demoted) |
| p-0irbygdv | PASS | PASS | PASS | PASS |
| p-zyt0jprz | PASS | PASS | PASS | PASS |

S7 "before" ran with 0 LLM redo rounds, so production S7 would have spent 2 LLM
rounds and then raised; "after" demotes the leftovers instead of dead-ending.

## Graph integrity findings (`storygraph/graph_integrity.py`, rebuilt state)

| Production | noop_fact | cast_location (stored → rebuilt) | opening_gap (stored → rebuilt) | raw_id | orphan | implicit_entry |
|---|---|---|---|---|---|---|
| p-og5klsx9 | 89 | 2 → 0 | 0 | 0 | 1 (`obj_clockwork_tree`) | 2 |
| p-pzbfjudf | 139 | 3 → 0 | 0 | 0 | 0 | 4 |
| p-a78w16oy | 149 | 0 | 0 | 5 (`obj_glowing_jewel` in scene text) | 0 | 0 |
| p-0irbygdv | 105 | 0 | 2 → 0 | 0 | 0 | 0 |
| p-zyt0jprz | 131 | 0 | 4 → 0 | 0 | 0 | 0 |

No contradictions or objects-without-lifecycle in any production.

## What generalizes

- **Event replay + clip windows** (state at clip open/close) hold across all genres.
- **Integrity checks** are schema-level (effects, facts, shots, text), not story-level.
- **Unrenderable-only blocking**: no production had a missing location, empty cast for
  character actions, or an empty spec. Every real blocker was a quality issue.

## What was overfit to the kitchen story

1. **Single-location assumption.** The kitchen story stays in one room, so no event ever
   had to move cast between scenes. Multi-location stories fail when scene N+1 starts
   somewhere new and no event says so (incident shape: clip 1 of scene 4 plays no Event,
   so its state was the previous scene's closing state).
2. **Species lexicon.** Built for "robot vs dog". It read "slick **bark**" (a tree) as
   barking, classified a "vanara **prince**" as a person because of the word "prince",
   and had no hybrid/mythic kind.
3. **Hard stops.** S6/S7 raised after their redo budget, even for clips that could render.

## Fixes applied

- `timeline/scene_entry.py` + `state.rebuild_state_facts`: **implicit scene entry**. When
  a scene opens, everyone present in it moves to the scene location (and so does anything
  they are holding). The move happens at the scene's entry order (`scene_entry:<scene>`
  facts). The exception is a character whose entrance is an explicit Event and who is not
  on screen before it.
- `validate.py` V3: checks the clip's **opening** state (scene-entry aware). An entrance
  played inside the clip is allowed. The closing check is kept. Messages name shot + reason.
- `clips/verb_use.py`: noun uses ("the rough bark") and speech idioms ("barks an order",
  "growls a warning", "roars with laughter", `barks: "…"`) are not vocalizations.
- `clips/species.py`: species is read first from explicit attributes (`species`/`kind`/…).
  Adds a **HYBRID** kind (vanara, centaur, sprite, clothed/upright animals) that can speak
  and may vocalize. "mechanical"/"clockwork" count as robot.
- `pipeline/validate_stage.py` (S6):
  - Species issues trigger a scene-scoped Screenwriter rewrite with the rule message.
  - Other issues trigger the usual stage redo.
  - Then it applies deterministic fixes (V6/V7/V9/position collisions).
  - Anything left is **demoted** to `Shot.lint_issues` (`source=S6`, `status=demoted`)
    plus an `S6_VALIDATE` report.
  - Only `U_NO_LOCATION`/`U_NO_CAST`/`U_EMPTY_SPEC` block.
- `pipeline/lint_stage.py` (S7): rebuilds state before compiling and demotes leftover
  lint issues after the final round (same unrenderable-only blocking).
- Integrity report runs after S5 (`S5_INTEGRITY` stage QA report) and is shown in the
  snapshot (`story_graph.graph_integrity`).

## p-0irbygdv (46 QA-failed runs): did the graph contribute?

- After rebuild, the graph is clean.
- The **stored** facts had 2 opening gaps (stale `holding` state between adjacent
  clips). p-zyt0jprz had 4.
- `shot_scn_001_02` (0irbygdv) failed with object_state×2, step_not_done×2 and
  pose_jump×9. Kitchen shots `004_02` and `004_03` failed with object_state, missing_object
  and continuity_break. All of these sat on those stale windows.
- S7 now rebuilds state before compiling. Repair-time respec (`repair/*`) should do the
  same.
- Its other defects come from render/audio, not the graph: line_missing 41, pose_jump 36,
  unscripted_action 13.

## Open items

- `noop_fact` volume (89–149 per story): the supervisor restates location/wearing on
  every event. Replay drops these restatements, but the prompts should stop producing
  them.
- Remaining S7 lint findings are general compiler issues ("Hanuman Hanuman's"
  possessive lead, symbol leaks "holds S2", unlisted held objects). They are demoted now,
  but the compiler should fix them at source.
