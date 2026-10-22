## Means over cases (±sd)
| dimension | V1_json | V2_prose | V3_hybrid | V4_minimal |
|---|---|---|---|---|
| action_adherence.eval | 0.69 ±0.24 | 0.81 ±0.24 | 0.92 ±0.22 | 0.71 ±0.34 |
| action.frames | 0.65 ±0.35 | 0.59 ±0.21 | 0.90 ±0.19 | 0.81 ±0.35 |
| object_permanence.eval | 0.81 ±0.17 | 0.79 ±0.15 | 0.90 ±0.14 | 0.54 ±0.25 |
| objects.frames | 0.53 ±0.28 | 0.55 ±0.33 | 0.78 ±0.32 | 0.41 ±0.30 |
| character_consistency.eval | 0.95 ±0.05 | 0.90 ±0.10 | 0.93 ±0.05 | 0.69 ±0.40 |
| character.frames | 0.95 ±0.03 | 0.91 ±0.08 | 0.92 ±0.13 | 0.91 ±0.17 |
| camera_adherence.eval | 0.79 ±0.18 | 0.88 ±0.16 | 0.88 ±0.16 | 0.42 ±0.36 |
| camera.frames | 0.31 ±0.43 | 0.56 ±0.39 | 0.62 ±0.48 | 0.00 ±0.00 |
| temporal_consistency.eval | 0.76 ±0.26 | 0.88 ±0.14 | 0.88 ±0.22 | 0.44 ±0.10 |
| cuts.ffmpeg | 0.81 ±0.35 | 1.00 ±0.00 | 1.00 ±0.00 | 0.12 ±0.33 |
| cuts.judge | 0.75 ±0.35 | 0.94 ±0.17 | 0.88 ±0.33 | 0.00 ±0.00 |
| script_adherence.eval | 0.80 ±0.16 | 0.88 ±0.13 | 0.94 ±0.13 | 0.83 ±0.14 |
| dialogue.transcript | 0.99 ±0.02 | 0.99 ±0.02 | 0.99 ±0.02 | 0.99 ±0.02 |
| overall | 0.85 ±0.09 | 0.88 ±0.09 | 0.93 ±0.07 | 0.74 ±0.12 |
| gate_passed | 0.12 ±0.22 | 0.19 ±0.35 | 0.38 ±0.48 | 0.00 ±0.00 |

## Paired delta vs V1 (mean [95% bootstrap CI] wins/losses over cases)
| dimension | V2_prose − V1 | V3_hybrid − V1 | V4_minimal − V1 |
|---|---|---|---|
| action_adherence.eval | +0.12 [+0.00,+0.31] 2W/0L | +0.23 [+0.04,+0.42] 4W/1L | +0.02 [-0.23,+0.27] 3W/2L |
| action.frames | -0.05 [-0.26,+0.20] 1W/4L | +0.25 [+0.00,+0.53] 3W/0L | +0.17 [-0.16,+0.50] 3W/1L |
| object_permanence.eval | -0.02 [-0.08,+0.03] 1W/2L | +0.09 [-0.02,+0.23] 4W/1L | -0.27 [-0.42,-0.12] 0W/6L |
| objects.frames | +0.02 [-0.18,+0.23] 3W/3L | +0.25 [-0.04,+0.54] 4W/1L | -0.12 [-0.40,+0.23] 1W/5L |
| character_consistency.eval | -0.05 [-0.11,-0.00] 2W/5L | -0.02 [-0.03,-0.01] 1W/5L | -0.25 [-0.57,-0.03] 0W/6L |
| character.frames | -0.03 [-0.09,+0.01] 2W/4L | -0.03 [-0.12,+0.04] 4W/3L | -0.04 [-0.17,+0.06] 3W/2L |
| camera_adherence.eval | +0.08 [-0.04,+0.23] 3W/1L | +0.08 [+0.02,+0.17] 4W/0L | -0.38 [-0.60,-0.13] 1W/6L |
| camera.frames | +0.25 [+0.06,+0.50] 3W/0L | +0.31 [-0.06,+0.75] 3W/1L | -0.31 [-0.62,+0.00] 0W/3L |
| temporal_consistency.eval | +0.12 [-0.09,+0.35] 4W/2L | +0.12 [+0.02,+0.24] 3W/0L | -0.32 [-0.53,-0.09] 1W/6L |
| cuts.ffmpeg | +0.19 [+0.00,+0.44] 2W/0L | +0.19 [+0.00,+0.44] 2W/0L | -0.69 [-1.00,-0.38] 0W/6L |
| cuts.judge | +0.19 [-0.12,+0.50] 3W/1L | +0.12 [-0.12,+0.44] 2W/1L | -0.75 [-0.94,-0.50] 0W/7L |
| script_adherence.eval | +0.08 [+0.02,+0.15] 5W/1L | +0.14 [+0.01,+0.27] 4W/2L | +0.03 [-0.11,+0.19] 4W/3L |
| dialogue.transcript | +0.00 [+0.00,+0.00] 0W/0L | +0.00 [+0.00,+0.00] 0W/0L | +0.00 [+0.00,+0.00] 0W/0L |
| overall | +0.03 [-0.02,+0.08] 5W/2L | +0.07 [+0.03,+0.13] 6W/2L | -0.11 [-0.18,-0.05] 1W/7L |
| gate_passed | +0.06 [+0.00,+0.19] 1W/0L | +0.25 [+0.06,+0.50] 3W/0L | -0.12 [-0.31,+0.00] 0W/2L |

## Per case: overall
| case (overall) | category | V1_json | V2_prose | V3_hybrid | V4_minimal |
|---|---|---|---|---|---|
| c1_walk (shot_scn_001_01) | locomotion | 0.85 | 0.80 | 0.98 | 0.84 |
| c2_prop (shot_scn_005_01) | small_prop | 0.96 | 0.96 | 0.96 | 0.82 |
| c3_twochar (shot_scn_005_02) | two_character | 0.95 | 0.97 | 0.96 | 0.81 |
| c4_dialogue (shot_scn_003_01) | dialogue | 0.74 | 0.77 | 0.87 | 0.47 |
| c5_closeup (shot_scn_004_03) | close_up | 0.87 | 0.89 | 0.99 | 0.85 |
| c6_chained (shot_scn_004_02) | chained | 0.74 | 0.94 | 0.93 | 0.76 |
| c7_ws_enter (shot_scn_001_01) | locomotion | 0.94 | 0.98 | 0.97 | 0.74 |
| c8_physics (shot_scn_002_01) | small_prop | 0.78 | 0.73 | 0.77 | 0.63 |

## Per case: action.frames
| case (action.frames) | category | V1_json | V2_prose | V3_hybrid | V4_minimal |
|---|---|---|---|---|---|
| c1_walk (shot_scn_001_01) | locomotion | 1.00 | 0.75 | 1.00 | 1.00 |
| c2_prop (shot_scn_005_01) | small_prop | 0.75 | 0.50 | 1.00 | 1.00 |
| c3_twochar (shot_scn_005_02) | two_character | 1.00 | 1.00 | 1.00 | 1.00 |
| c4_dialogue (shot_scn_003_01) | dialogue | 0.25 | 0.25 | 1.00 | 1.00 |
| c5_closeup (shot_scn_004_03) | close_up | 1.00 | 0.50 | 1.00 | 1.00 |
| c6_chained (shot_scn_004_02) | chained | 0.00 | 0.75 | 1.00 | 1.00 |
| c7_ws_enter (shot_scn_001_01) | locomotion | 0.50 | 0.50 | 0.50 | 0.50 |
| c8_physics (shot_scn_002_01) | small_prop | 0.67 | 0.50 | 0.67 | 0.00 |

## Per case: objects.frames
| case (objects.frames) | category | V1_json | V2_prose | V3_hybrid | V4_minimal |
|---|---|---|---|---|---|
| c1_walk (shot_scn_001_01) | locomotion | 1.00 | 0.88 | 1.00 | 0.50 |
| c2_prop (shot_scn_005_01) | small_prop | 0.75 | 0.25 | 0.75 | 0.25 |
| c3_twochar (shot_scn_005_02) | two_character | 0.50 | 0.88 | 1.00 | 0.00 |
| c4_dialogue (shot_scn_003_01) | dialogue | 0.50 | 0.50 | 0.00 | 0.50 |
| c5_closeup (shot_scn_004_03) | close_up | 0.50 | 1.00 | 1.00 | 0.17 |
| c6_chained (shot_scn_004_02) | chained | 0.00 | 0.08 | 0.83 | 1.00 |
| c7_ws_enter (shot_scn_001_01) | locomotion | 0.67 | 0.67 | 0.67 | 0.67 |
| c8_physics (shot_scn_002_01) | small_prop | 0.33 | 0.17 | 1.00 | 0.17 |

## Per case: cuts.ffmpeg
| case (cuts.ffmpeg) | category | V1_json | V2_prose | V3_hybrid | V4_minimal |
|---|---|---|---|---|---|
| c1_walk (shot_scn_001_01) | locomotion | 1.00 | 1.00 | 1.00 | 0.00 |
| c2_prop (shot_scn_005_01) | small_prop | 1.00 | 1.00 | 1.00 | 0.00 |
| c3_twochar (shot_scn_005_02) | two_character | 1.00 | 1.00 | 1.00 | 0.00 |
| c4_dialogue (shot_scn_003_01) | dialogue | 0.00 | 1.00 | 1.00 | 0.00 |
| c5_closeup (shot_scn_004_03) | close_up | 1.00 | 1.00 | 1.00 | 0.00 |
| c6_chained (shot_scn_004_02) | chained | 1.00 | 1.00 | 1.00 | 1.00 |
| c7_ws_enter (shot_scn_001_01) | locomotion | 0.50 | 1.00 | 1.00 | 0.00 |
| c8_physics (shot_scn_002_01) | small_prop | 1.00 | 1.00 | 1.00 | 0.00 |
