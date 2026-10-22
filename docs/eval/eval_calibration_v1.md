# Eval calibration v1: S9 eval gate vs golden set v1

Golden data: [labels.jsonl](../../productions_service/eval_data/golden/v1/labels.jsonl)
(66 clips, 15 shots; review notes in [golden_set_v1.md](golden_set_v1.md)).
Tuned gate: `eval:` in [default.yaml](../../productions_service/storygraph/config/default.yaml).
Pre-calibration gate (baseline): [baseline_gate_v0.yaml](eval_calibration_v1/baseline_gate_v0.yaml).
Code: [`storygraph/eval/calibration/`](../../productions_service/storygraph/eval/calibration/).
Regression test: [test_golden_agreement.py](../../productions_service/tests/eval/test_golden_agreement.py).

> [!CAUTION]
> The golden labels were made by an agent and have not had a human review yet (34 clips are
> on the review list in golden_set_v1.md). Golden v1 also has only **one** strict pass. All
> numbers below are therefore against the **kids-draft acceptable** label (29 of 66 clips).
> Strict-pass precision and recall are reported for completeness but are statistical noise.

## Method
1. **Re-score.** All 66 clips were re-scored with the current engine through
   `python -m storygraph.eval.calibration score`, using real Vertex (project `aug18-25-3`).
   - The engine is built exactly as `storygraph.eval.run` builds it: `gemini-3.8-flash`
     critic, the Vertex image embedder, `GeminiTranscriber` (flash with a pro fallback, the
     latest transcript and dialogue-merge code) and CV checks.
   - Inputs match what S9 sends: the compiled spec (`generation_runs.compiled_prompt`, or
     the review manifest for the 13 legacy clips), up to 6 labelled reference sheets, and the
     style guide.
   - Previous-clip context is the last frame of the predecessor shot's approved take (39 of
     66 clips have one).
   - Results go to a JSONL cache (`CachedScore`, the full `EvalReport`). Re-runs only score
     clips that are missing or that errored. Two clips hit transient 429s and were re-scored.
2. **Agreement.** The engine verdict is compared with the golden labels:
   - pass/fail precision, recall and F1, against kids-draft acceptable and against strict
     pass;
   - per dimension: Spearman between the engine score and the golden 1–5 score, plus a pass
     confusion matrix (engine `score >= threshold` vs golden dimension pass);
   - defect hit rate: for each golden tag of medium severity or worse, the share of tagged
     clips where the engine flags that dimension (a medium/high defect, or a score below
     threshold).
3. **Search.** The search is coordinate descent over capped, monotone grids:
   - per-dimension hard gate on/off with a threshold in 0.30–0.90, at most ±0.25 from
     baseline;
   - weight × {0.25, 0.5, 1, 1.5, 2};
   - per-dimension `demote_high_defects`, a new knob: that dimension's HIGH defects count as
     MEDIUM in the defect gate;
   - overall threshold 0.50–0.85;
   - `max_medium_defects` 1–5.

   Camera is never offered as a hard gate. A move is kept only if it strictly improves the
   objective, so ties stay with the baseline.
4. **Validation.** Leave-one-shot-out cross-validation (15 folds). All takes of a shot are
   held out together, so near-duplicate takes cannot leak between train and test. Every
   "held-out" number below comes from these out-of-fold verdicts.

### Objective: why not "precision ≥ 0.8, then best recall"
The requested primary target was kids-draft pass precision ≥ 0.8 with the best recall. On
this engine and label set, that target cannot be validated:
- **Held out, the floor objective overfits.** Each training fold finds a gate that passes
  only 2–4 clips at precision 1.0. Out of fold, it scores precision 0.50 and recall 0.14
  (table below).
- **The engine's ranking cannot support it.** Sorting all 66 clips by engine overall score,
  precision reaches 0.80 only in the top 5 clips (recall 0.14). After that it stays between
  0.55 and 0.67. The AUC of the overall score for kids-OK is 0.65.

The shipped gate therefore maximises the precision-weighted **F0.5** on kids-draft
acceptable, with strict F1 and then accuracy as tie-breaks. This beats the baseline on both
precision and recall held out, and it beat the floor objective on every metric. The floor
mode is still available (`Objective(mode="floor")`) and is re-reported in every run.

## Headline (kids-draft acceptable is the positive class)

| Gate | Pass rate | Precision | Recall | F1 | Accuracy |
|---|---|---|---|---|---|
| Baseline (pre-calibration) | 0.21 | 0.50 | 0.24 | 0.33 | 0.56 |
| **Calibrated, held-out (LOSO)** | 0.33 | **0.64** | **0.48** | **0.55** | **0.65** |
| Calibrated, in-sample (shipped config, 66 clips) | 0.38 | 0.76 | 0.66 | 0.70 | 0.76 |
| Floor objective (P ≥ 0.8), held-out | 0.12 | 0.50 | 0.14 | 0.22 | 0.56 |

Strict pass, with only 1 golden positive: the baseline passed 14 clips and none was the
strict pass. The calibrated gate passes 25 and includes it in-sample, but not held out.

> [!IMPORTANT]
> The **held-out** row is the honest estimate. The regression test floors are set to those
> numbers: P ≥ 0.636, R ≥ 0.483, F1 ≥ 0.549. A sensitivity test checks that the old gate
> fails these floors.

## What changed (baseline → calibrated)

| Knob | Baseline | Calibrated | Fold stability (15 LOSO folds) |
|---|---|---|---|
| `action_adherence.hard_gate` | true | **false** | kept off in 14/15 |
| `action_adherence.demote_high_defects` | – | **true** | |
| `object_permanence.demote_high_defects` | – | **true** | |
| `script_adherence.hard_gate` | true | **false** | kept off in 13/15 |
| `character_consistency.threshold` | 0.65 | **0.70** | 0.70 in all folds (hard 15/15) |
| `max_medium_defects` | 2 | **3** | 3 in 13/15 (1 and 4 once each) |
| overall threshold, weights, others | unchanged | unchanged | overall 0.65 in all folds |

Temporal and character remain hard gates (15/15 folds). Object permanence remains a hard
gate, but its HIGH defects no longer block on their own. Camera stays at threshold 0 with no
hard gate. No weight change survived: the weights did not affect agreement once the gates
were set.

## Per-dimension findings (engine vs golden, all 66 clips)

| Dimension | n | Spearman | Engine mean | Confidence | Golden fail rate | Pass accuracy | Engine pass / golden fail | Engine fail / golden pass |
|---|---|---|---|---|---|---|---|---|
| physical_plausibility | 66 | 0.44 | 0.87 | 0.70 | 0.17 | 0.83 | 9 | 2 |
| camera_adherence | 66 | 0.41 | 0.86 | 0.70 | 0.68 | 0.32* | 45 | 0 |
| script_adherence | 58 | 0.40 | 0.83 | 0.79 | 0.12 | 0.90 | 3 | 3 |
| action_adherence | 66 | 0.39 | 0.75 | 0.75 | 0.55 | 0.62 | 20 | 5 |
| scene_consistency | 66 | 0.38 | 0.84 | 0.79 | 0.38 | 0.62 | 17 | 8 |
| object_permanence | 66 | 0.31 | 0.73 | 0.75 | 0.38 | 0.68 | 14 | 7 |
| temporal_consistency | 66 | 0.30 | 0.82 | 0.90 | 0.29 | 0.70 | 10 | 10 |
| character_consistency | 66 | 0.28 | 0.74 | **0.90** | 0.67 | 0.42 | 38 | 0 |
| spatial_consistency | 66 | 0.22 | 0.93 | 0.60 | 0.18 | 0.83 | 11 | 0 |
| audio | 66 | 0.11 | 0.98 | 0.80 | 0.12 | 0.88 | 8 | 0 |
| style_consistency | 66 | 0.08 | 0.97 | 0.70 | 0.03 | 0.97 | 2 | 0 |

\*Camera threshold is 0.0 by design, so the engine always "passes" camera.

**Reliable enough to gate on:** character (as a floor), temporal and physics.
- **Character** is the most useful single signal for kids-OK (AUC 0.73), even though its
  Spearman is low. Raising the floor from 0.65 to 0.70 was chosen in every fold.
- **Temporal** catches 8 of 12 golden hard cuts (`hard_cut` is medium severity). Physics
  `physics_floating` HIGH appeared in 7 clips, none of them kids-OK.

**Unreliable; down-weight or treat as low confidence:**
- **action_adherence.** Its AUC for kids-OK is 0.51, which is chance. `step_not_done` HIGH
  fires on 14 kids-OK clips and 22 not-OK clips (39% vs a 44% base rate). It does catch
  ACT_STEP_MISSING (9/10), but it cannot tell a draft-acceptable partial beat from a broken
  one. That is why it is no longer a hard gate and its HIGH defects are demoted.
- **object_permanence.** AUC 0.53. `object_state`/`extra_object` HIGH fire on 19 kids-OK
  clips and 28 not-OK clips. Its hit rates on real duplicates and pop-ins are good (0.78 and
  0.83), so it stays as a hard gate on score but no longer blocks through HIGH defects.
- **character_consistency.** Confidence is high (0.90) but it is badly calibrated. It
  catches only 16% of CHAR_FEATURE_ADDED (Pip's visor mouth, 38 clips) and 36% of
  CHAR_OFF_MODEL_REF. This is the largest remaining source of false passes. It needs a
  rubric or prompt fix (an explicit "no mouth" feature check), not a different threshold.
- **camera_adherence.** Detection is modest (30% CAM_SIZE_WRONG, 0% CAM_ANGLE_WRONG). It
  stays informational only.
- **style, audio and spatial.** They are near ceiling with Spearman ≤ 0.22, so they carry
  almost no information on this set. Spatial misses every SPAT_POSITION_JUMP and every
  SPAT_SCREEN_SIDE_WRONG.
- **scene_consistency.** It misses most SCENE_SETTING_MISMATCH (36% hit) and
  SCENE_PREV_SHOT_BREAK (17%), even though prev-frame context was supplied.

### Defect-type hit rates (golden tag, medium severity or worse; engine flags that dimension)

| Dimension | Golden tag | n | Hit rate |
|---|---|---|---|
| character | CHAR_FEATURE_ADDED | 38 | 0.16 |
| camera | CAM_SIZE_WRONG | 27 | 0.30 |
| action | ACT_INCOMPLETE | 25 | 0.60 |
| scene | SCENE_SETTING_MISMATCH | 22 | 0.36 |
| character | CHAR_OFF_MODEL_REF | 14 | 0.36 |
| action | ACT_UNSCRIPTED | 13 | 0.46 |
| camera | CAM_MOVE_WRONG | 13 | 0.38 |
| temporal | TEMP_HARD_CUT | 12 | 0.67 |
| camera | CAM_UNREQUESTED_CUT | 11 | 0.64 |
| scene | SCENE_OPENING_STATE_WRONG | 11 | 0.36 |
| action | ACT_STEP_MISSING | 10 | 0.90 |
| object | OBJ_DUPLICATE | 9 | 0.78 |
| camera | CAM_ANGLE_WRONG | 6 | 0.00 |
| object | OBJ_POP_IN | 6 | 0.83 |
| scene | SCENE_PREV_SHOT_BREAK | 6 | 0.17 |
| object | OBJ_REQUIRED_MISSING | 5 | 0.40 |

## Remaining disagreements (calibrated gate, in-sample: 6 false passes, 10 false fails)
**False passes (engine passes, golden says not kids-acceptable):**
- `legacy_shot_scn_001_02_att8` and `legacy_shot_scn_002_02_att1`: off-model Pip with a
  full cartoon face. The character scores are still ≥ 0.70 (see the character finding).
- `run_shot_scn_004_01_att1_580846`: a hard cut at about 5.9s that is visible only at 12 fps.
  Both ffmpeg and the VLM miss it.
- `run_shot_scn_002_01_att4_37168d` and `run_shot_scn_001_01_att1_e10ebc`: missing or
  contradicted beats (golden action ≤ 2). The engine scored action ≥ 0.9.
- `run_shot_scn_006_02_att2_aac6ea`: a 3D CG render (golden style 2). The engine's style
  score stayed high.

**False fails (golden kids-OK, engine blocks):**
- 8 are blocked by temporal, object or character hard gates, usually on `morphing` or
  `extra_object`, e.g. `run_shot_scn_002_03_att1_0d4a77` and `run_shot_scn_005_02_att2_5e234d`.
- 2 are blocked by the defect gate: one HIGH defect, or a pile-up of 4–6 medium defects
  (demoted action/object defects plus script `unscripted_action`/`beat_missing`), e.g.
  `run_shot_scn_004_03_att2_ec94c0`.

## Caveats
- **Labels.** These are agent silver labels pending human review. The two open calibration
  questions in golden_set_v1.md (is a brief visor smile a 3 or a 4, and does the music flag
  count) move about 12 labels. Re-run the calibration once a human confirms them.
- **Sample size.** 66 clips from one production, 15 shots, one location and two characters.
  The held-out confidence intervals are wide (14 true positives held out). Treat the floors
  as regression guards, not as quality claims.
- **Engine variance.** The VLM is not deterministic. Scores come from a single run per clip,
  and nobody measured re-run variance.
- **Legacy clips** were scored against their original compiled prompts, which set
  `has_mouth: true`. Golden counts the resulting faces as defects, so the engine is judged
  against the intent rather than the prompt.

## Reproduce
```bash
cd productions_service
# 1) re-score (cached; only missing/errored clips are re-run)
python -m storygraph.eval.calibration score --jobs golden_jobs.jsonl --cache engine_scores_v1.jsonl
# 2) agreement + LOSO search + fixture refresh
python -m storygraph.eval.calibration report --cache engine_scores_v1.jsonl \
  --base-config ../docs/eval/eval_calibration_v1/baseline_gate_v0.yaml \
  --out report.json --fixture tests/eval/fixtures/golden_v1_engine_scores.jsonl
```
`golden_jobs.jsonl` holds `ScoreJob` records: clip path, compiled spec, labelled reference
PNGs, previous-clip path and style guide. It was built from the labeler's cached clips and
the Firestore exports. If Vertex rejects ADC with "requires a quota project", set
`quota_project_id` in the credentials file.
