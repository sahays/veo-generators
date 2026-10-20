# Golden set v1 — video-generation eval labels

Human-style labels for every rendered clip of production `p-zyt0jprz`
(Firestore `aug18-25-3`), judged **independently of the pipeline critic**
from frames (3 fps contact sheets + first/last frames), ffmpeg scene-cut /
silence / volume analysis, a Gemini audio transcript, and the reference
sheets. Critic verdicts were only read afterwards to compute agreement
(see `docs/eval/golden_set_v1.md`).

## Files
| File | Content |
|---|---|
| `taxonomy.json` | Fixed defect taxonomy (tags per dimension), 1–5 scale, pass/kids-draft rules, severity and attribution enums. |
| `labels.jsonl` | One JSON record per generation run (clip). |

## `labels.jsonl` record
| Field | Type | Notes |
|---|---|---|
| `run_id` | str | Firestore `generation_runs` id; `legacy_<shot>_att<n>` for earlier reviewed clips no longer in Firestore. |
| `shot_id`, `attempt` | str, int | |
| `source` | `firestore_current` \| `legacy_review` | |
| `video_uri` | str \| null | `gs://` URI (null for legacy clips without a surviving run doc). |
| `spec_hash` | str | `shot_content_hash` of the run; sha256 of the compiled prompt for legacy clips. |
| `package_hash` | str \| null | Render package hash. |
| `duration_s` | float | Rendered duration. |
| `observed` | str | Plain description of what happens, with timestamps. |
| `dimensions` | object | Keys: `character_consistency`, `temporal_consistency`, `spatial_consistency`, `scene_consistency`, `object_permanence`, `physical_plausibility`, `action_adherence`, `camera_adherence`, `style_consistency`, `audio`, `script_adherence`. |
| `dimensions.<d>.score` | int 1–5 | See `taxonomy.json#scale`. |
| `dimensions.<d>.pass` | bool | `score >= 4` and no `high`/`blocker` defect (recomputed at build time). |
| `dimensions.<d>.na` | bool | Only `script_adherence` when the spec has no speech. |
| `dimensions.<d>.defects[]` | list | `{tag, severity, t_start_s, t_end_s, evidence, attribution, attribution_reason}`; `tag` ∈ taxonomy, `attribution` ∈ `prompt_spec\|omni_limit\|reference\|pipeline\|unknown`. |
| `overall.pass` | bool | All dimensions pass. |
| `overall.kids_draft_acceptable` | bool | No blocker, no dimension ≤ 2, nothing objectionable. |
| `overall.borderline` / `borderline_reason` | bool / str | Flagged for human review. |
| `overall.confidence` | `low\|med\|high` | |
| `labeler`, `labeled_at`, `taxonomy_version` | str | `agent`, ISO-8601 UTC, `golden-v1`. |

## Usage
Score a critic/evaluator by joining on `run_id` (or `video_uri`) and
comparing `overall.pass` and per-dimension `pass`. Treat
`overall.borderline=true` records as soft labels until a human confirms them.
Clips are not committed; fetch with `gcloud storage cp <video_uri> .`.
