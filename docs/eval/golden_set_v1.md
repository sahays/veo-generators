# Golden set v1: video-generation eval (production `p-zyt0jprz`)

Data: [labels.jsonl](../../productions_service/eval_data/golden/v1/labels.jsonl) ·
[taxonomy.json](../../productions_service/eval_data/golden/v1/taxonomy.json) ·
[schema README](../../productions_service/eval_data/golden/v1/README.md)

## Method
- **Scope:** 66 clips across 15 shots.
  - 53 are every `generation_runs` doc that has a video (Firestore, as of 2026-10-20).
  - 13 are earlier-reviewed legacy clips. Their prior findings were re-verified, not copied.
- **Evidence for each clip:**
  - Frames at 3 fps in a timestamped contact sheet, plus the first and last frame at 640px. Labelers pulled extra frames up to 12 fps where it was ambiguous.
  - ffmpeg scene-cut detection (`scene>0.3`), `silencedetect`, and `volumedetect`.
  - A gemini-2.5-pro **audio-only transcription** (utterances, voice, sfx, music flag).
  - The reference sheets for characters, props, and the location.
- **Independence:** labels were made without access to critic outputs. The critic's `qa_scores` were joined only afterwards, for the agreement section.
- **Scoring:** each of the 11 dimensions gets a score from 1 to 5 and pass/fail.
  - A dimension passes when its score is at least 4 and it has no high or blocker defect.
  - Overall pass means every dimension passes.
  - Each defect is timestamped and attributed (`prompt_spec | omni_limit | reference | pipeline`).
- **Labeler:** an agent (7 parallel labelers sharing one contract). Treat these as silver labels until the review list below is confirmed by a human.

## Headline
| | Count |
|---|---|
| Clips labeled | 66 (53 current, 13 legacy) |
| Overall **pass** (strict) | **1** (`run_shot_scn_006_01_att2_5813ac`, borderline) |
| **Acceptable for a kids' film draft** | **29** (28 of 53 current, 1 of 13 legacy) |
| Shots with ≥1 kids-draft-acceptable take | 12 / 15 |
| Clips failing exactly 1 dimension | 10 (the closest-to-pass pool) |
| Defects logged | 503 (208 low, 208 med, 87 high) |

## Per-dimension pass rate (golden)
| Dimension | Pass rate | Mean score | Top tags |
|---|---|---|---|
| character_consistency | **33%** | 3.38 | CHAR_FEATURE_ADDED (45 clips), CHAR_OFF_MODEL_REF |
| temporal_consistency | 71% | 4.02 | TEMP_DURATION_MISMATCH, TEMP_HARD_CUT |
| spatial_consistency | 82% | 4.35 | SPAT_POSITION_JUMP, SPAT_SCREEN_SIDE_WRONG |
| scene_consistency | 62% | 3.70 | SCENE_SETTING_MISMATCH, SCENE_OPENING_STATE_WRONG |
| object_permanence | 62% | 3.94 | OBJ_DUPLICATE, OBJ_REQUIRED_MISSING |
| physical_plausibility | 83% | 4.41 | PHYS_IMPOSSIBLE_MOTION |
| action_adherence | **45%** | 3.36 | ACT_INCOMPLETE, ACT_UNSCRIPTED, ACT_STEP_MISSING |
| camera_adherence | **32%** | 3.27 | CAM_SIZE_WRONG, CAM_MOVE_WRONG, CAM_UNREQUESTED_CUT |
| style_consistency | 97% | 4.83 | (rare: 3D CG render in 006_02_att2) |
| audio | 88% | 4.42 | AUD_SFX_MISSING, AUD_MUSIC_UNWANTED |
| script_adherence | 89% | 4.48 | SCRIPT_TIMING_WRONG |

## Top defect patterns
1. **Pip gets a mouth or visor smile** (CHAR_FEATURE_ADDED, 45 of 66 clips).
   - In current runs it shows even with `has_mouth:false` (omni_limit). For example, `run_shot_scn_005_02_att4_291fc9` has a cyan smile line on the visor from 5.7 to 7.0s.
   - Legacy specs set `lipsync/has_mouth:true`, which produced full cartoon faces (prompt_spec). See `legacy_shot_scn_001_01_att4` at 5.0–7.3s.
   - *Sensitivity:* if a brief visor smile were accepted (score 4), strict passes would rise from 1 to 5.
2. **Scripted beats incomplete or story outcome violated** (ACT_INCOMPLETE 50, ACT_UNSCRIPTED 23).
   - In `run_shot_scn_001_02_att2_7986cf` at 4.8s, Pip reaches the bowl when the end_state says he must fail.
   - Milo wakes and barks in 6 of 10 scene-1 clips when he should be asleep, e.g. `run_shot_scn_001_01_att1_e10ebc` at 1.7s.
   - In all four 003_02 runs, Pip deliberately pours the glass instead of knocking it by accident.
3. **Camera spec ignored** (CAM_SIZE_WRONG 34, CAM_MOVE_WRONG 21).
   - MCU or low-angle requests are rendered as wide, eye-level two-shots, e.g. every 005_02 attempt.
   - 25 of 78 camera defects are prompt_spec: an MCU on the glass cannot also show the floor puddle (003_02, 004_03).
4. **Setting does not match the plate, or the opening state is wrong** (39 and 20 defects).
   - The table shape changes and the kitchen layout varies between takes.
   - `run_shot_scn_002_03_att4_cce7eb` swaps the kitchen for a reference-sheet leaf backdrop (reference).
5. **Hard cuts inside single-take specs** (TEMP_HARD_CUT 12, CAM_UNREQUESTED_CUT 11).
   - The `scene>0.3` detector **missed several**; they were caught only at 12 fps. For example, `run_shot_scn_004_01_att1_580846` has a cut at about 5.9s.
6. **Duration buckets.** Omni returns about 7.19, 7.64, 8.62, or 9.63s.
   - A spec of 8.5s gives 7.64s, which is −10.1%, just over the threshold. This affects 20 clips and is attributed to pipeline.
   - The spec should snap to supported durations.
7. **Duplicated props** (OBJ_DUPLICATE 13). The towel stays on its peg while it is also in use, or splits in two (004_02 att2–4).

## Attribution
| Attribution | Defects | Share |
|---|---|---|
| omni_limit (model failed a clear spec) | 365 | 73% |
| prompt_spec (contradictory or wrong spec) | 82 | 16% |
| pipeline (duration, chaining) | 34 | 7% |
| reference (ref or first-frame image) | 21 | 4% |

prompt_spec is concentrated in camera (25 of 78), character (16 of 70; the legacy `has_mouth`/lipsync setting), object (12 of 46; e.g. "exactly one strawberry" vs the bowl), and scene (9).

Fixing the spec is cheap and should come first: snap durations, check that framing is compatible with the required props, never set `has_mouth` for Pip, and derive the object list from the screenplay. That would remove roughly a quarter of the defects before spending retries on Omni.

## Agreement with the pipeline critic (read after labeling)
The positive class is pass. The critic gate is `qa_scores.passed`.

| | golden pass | golden fail |
|---|---|---|
| **critic pass** | 0 | **11** |
| **critic fail** | 1 | 54 |

- **Precision of pass: 0/11 = 0%.** **Recall of pass: 0/1 = 0%.** Raw agreement is 82%, but only because almost everything fails.
- Against the softer *kids-draft acceptable* label, precision is 2/11 (18%) and recall is 2/29 (7%). The critic both lets through off-model clips and rejects watchable takes.
- 8 of the 11 false passes are legacy clips with off-model Pip faces.
  - Two are current runs. `run_shot_scn_002_02_att4_e3ad52` fails only action_adherence and is kids-OK. `run_shot_scn_004_01_att1_580846` has a hard cut the critic missed.

Per-dimension disagreement (critic field ≥ 0.75 mapped to pass):

| Dimension (critic field) | n | Disagree | Critic pass / golden fail | Critic fail / golden pass |
|---|---|---|---|---|
| character (identity, face, wardrobe) | 66 | 37 | 22 | 15 |
| temporal (hard_cut_times_s empty) | 53 | 12 | 12 | 0 |
| scene (setting_match, continuity_prev_shot) | 66 | 39 | 11 | 28 |
| object_permanence | 66 | 19 | 11 | 8 |
| physical_plausibility | 66 | **45** | 2 | **43** |
| action (action_achieved) | 66 | 28 | 23 | 5 |
| camera (camera_match) | 53 | 26 | 22 | 4 |
| script (dialogue_wer ≤ 0.25) | 66 | 7 | 7 | 0 |
| spatial / style / audio | n/a | | | (the critic has no signal) |

**What this suggests about the critic:**
- **Physics is too strict.** It sits around 0.68–0.72 on fine cartoon motion, causing 43 false fails.
- **Action and camera are too lenient.** They are near 1.0 even when beats or framing are wrong.
- **Character scoring can't see design changes.** Scores cluster at 0.70–0.75 and do not respond to a mouth appearing.
- **Hard-cut detection misses cuts** (12 false passes on temporal).
- **Spatial, style, and audio are not scored.**

## Please review these 34 clips
These are borderline labels and/or clips where the golden label and the critic disagree. Most hinge on two calibration questions:
- (a) Is a brief visor smile on Pip a score of 3 (fail) or 4 (pass)?
- (b) Does the transcript's `music_present` flag alone justify AUD_MUSIC_UNWANTED?

Answering those two would settle about 12 of the 34.

| # | run_id | golden | critic | why review |
|---|---|---|---|---|
| 1 | `run_shot_scn_001_01_att4_3b444b` | fail | fail | overall verdict hinges on whether Milo waking (no explicit stay-asleep end state) counts as med ACT_UNSCRIPTED |
| 2 | `legacy_shot_scn_001_01_att4` | fail | pass | character 2-vs-3 decides kids_draft; overall fail is clear |
| 3 | `run_shot_scn_001_02_att2_7986cf` | fail | fail | whether the hand actually touches the bowl at 4.8-5.3s is ambiguous at this resolution |
| 4 | `run_shot_scn_002_01_att2_a0bd40` | fail | fail | character_consistency 3-vs-4 (brief ~1s visor mouth) alone decides overall fail. |
| 5 | `legacy_shot_scn_002_01_att1` | fail | pass | critic pass vs golden fail (clear golden fail; confirm) |
| 6 | `run_shot_scn_002_02_att1_f2a91d` | fail | fail | action_adherence 3-vs-4 on whether Pip's unscripted walk-off is significant decides overall. |
| 7 | `run_shot_scn_002_02_att4_e3ad52` | fail | pass | action_adherence 3-vs-4: Milo stops Pip but stands beside/behind rather than in the chair's path; this alone decides overall. |
| 8 | `legacy_shot_scn_002_02_att1` | fail | pass | critic pass vs golden fail (clear golden fail; confirm) |
| 9 | `run_shot_scn_002_03_att1_0d4a77` | fail | fail | Chair transfer at 2.5-3.0s partly masked by camera pan; ambiguous at 3 fps. |
| 10 | `run_shot_scn_002_03_att4_cce7eb` | fail | fail | Scene 2-vs-3 call decides kids_draft; duration 10.1% is marginal. |
| 11 | `run_shot_scn_003_01_att2_e85d69` | fail | fail | Float lasts ~0.4s; could be read as a cartoon hop (2-vs-3 decides kids_draft). |
| 12 | `run_shot_scn_003_01_att3_10e504` | fail | fail | Overall verdict hinges on the 3-vs-4 call for the brief visor mouth (5.0-5.4s). |
| 13 | `legacy_shot_scn_003_01_att2` | fail | pass | Scene 2-vs-3 (prev-shot break) and action 2-vs-3 decide kids_draft. |
| 14 | `run_shot_scn_003_02_att2_551155` | fail | fail | overall fail hinges on 3-vs-4 calls for mouth visibility and MCU vs MS framing |
| 15 | `run_shot_scn_004_01_att1_580846` | fail | pass | cut detected only at 12fps (missed by scene detector); if judged a fast reframe, overall still fails on mouth and Milo side |
| 16 | `legacy_shot_scn_004_01_att5` | fail | pass | critic pass vs golden fail (clear golden fail; confirm) |
| 17 | `run_shot_scn_004_02_att2_b99967` | fail | fail | Duration 7.19s vs 8.0s is 10.1% short (just over threshold); towel splitting into two pieces at 5.7-6.7s ambiguous at 3 fps. |
| 18 | `legacy_shot_scn_004_02_att5` | fail | fail | Whether Pip pushes the chair at ~1.3-1.7s is ambiguous at 3 fps (chair ends near table but no visible push). |
| 19 | `run_shot_scn_004_03_att1_a0a18b` | fail | fail | Whether the large foreground puddle at 6.7-7.6s is a pop-in or the off-screen remainder of the original spill is ambiguous. |
| 20 | `run_shot_scn_004_03_att2_ec94c0` | fail | fail | Action adherence 3 vs 4 hinges on whether the faint leftover film counts as the 'missed slick' (it is mid-floor, not near the door). |
| 21 | `run_shot_scn_004_03_att4_d91a58` | fail | fail | Pip's visor smile/mouth at 3.5s and 7.0-7.6s scored 4 (brief) vs 3; camera size wrong is a spec contradiction. |
| 22 | `run_shot_scn_005_01_att1_936d96` | fail | fail | Character dimension hinges on whether a brief visor smile is a 3 or 4 |
| 23 | `run_shot_scn_005_01_att2_05f4be` | fail | fail | Character dimension hinges on whether a brief visor smile is a 3 or 4 |
| 24 | `run_shot_scn_005_01_att4_8213b1` | fail | fail | Character dimension hinges on whether a brief visor smile is a 3 or 4 |
| 25 | `legacy_shot_scn_005_01_att1` | fail | pass | critic pass vs golden fail (clear golden fail; confirm) |
| 26 | `run_shot_scn_005_02_att1_f830e2` | fail | fail | Audio fail rests on the transcript's music flag, which frames can't confirm |
| 27 | `run_shot_scn_005_02_att2_5e234d` | fail | fail | Audio fail rests on the transcript music flag |
| 28 | `run_shot_scn_005_02_att3_479d62` | fail | fail | Character and camera are both 3-vs-4 calls |
| 29 | `run_shot_scn_005_02_att4_291fc9` | fail | fail | Audio fail rests on the transcript music flag |
| 30 | `legacy_shot_scn_005_02_att1` | fail | pass | critic pass vs golden fail (clear golden fail; confirm) |
| 31 | `run_shot_scn_006_01_att2_5813ac` | pass | fail | Camera follow vs dolly is a 3-vs-4 call that decides overall pass. |
| 32 | `legacy_shot_scn_006_01_att1` | fail | pass | critic pass vs golden fail (clear golden fail; confirm) |
| 33 | `run_shot_scn_006_02_att3_509343` | fail | fail | Overall fails only on camera size (prompt_spec conflict); mouth is a 3-vs-4 call. |
| 34 | `legacy_shot_scn_006_02_att1` | fail | pass | Camera 2-vs-3 decides kids_draft. |

## Caveats
- **Frame rate:** 3 fps can miss sub-0.3s events. Labelers resampled at up to 12 fps only where they suspected something.
- **Audio:** audio judgements rely on a single Gemini transcription and were not verified with a second model. Music and sfx flags are the weakest evidence.
- **Legacy clips:** their critic used an older rubric (no `camera_match` or `hard_cut_times_s`), so those dimensions are n/a in the agreement table.
- **Base rate:** with 1 golden pass, precision and recall of pass have very wide uncertainty. Use the per-dimension table and the kids-draft view for critic tuning.
