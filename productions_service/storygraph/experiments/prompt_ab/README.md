# prompt_ab — controlled prompt-format A/B for Gemini Omni

Answers: *is our compiled prompt format a material cause of render failures, and which
prompt construction does Omni actually honour?* Results: `docs/eval/prompt_ab_v1.md`.

## Design guarantees

- **Only the prompt text varies.** Each variant is rendered through the production
  `GeminiVideoGenerator.generate` with an identical `RenderPackage` (same reference images,
  order, captions, `[# Sources/References]` header, first-frame tag, duration, 360p). The
  exact primary-rung request text is saved per render (`requests/*.txt`) with its sha.
- **One ground truth.** Every render is scored against the shot's compiled V1 spec, so
  variants are judged on the same intent.
- **Two independent scorers.** The deployed eval engine (`storygraph.eval.engine`) plus a
  model-free ffmpeg cut detector and a separate frame-checklist judge + free-text
  transcription (`frame_judge.py`).

## Variants (`variants/builders.py`)

| id | content |
|---|---|
| `V1_json` | production compact `OmniClipSpec` JSON (unchanged) |
| `V2_prose` | Omni-guide prose: single-shot directive, style, setting, tagged characters, counted props, opening state, `[a-bs]` timecoded beats with dialogue inline, camera, sound, short negatives |
| `V3_hybrid` | one prose paragraph (single take + style + ordered beats) + minimal block: CHARACTERS / OBJECTS (count, holder) / SETTING / CAMERA / DIALOGUE |
| `V4_minimal` | one paragraph: actions + dialogue only, ref tags on first mention |

All builders are pure functions of `(OmniClipSpec, has_first_frame)`; shared phrasing
(camera vocabulary, object/holder lines, beat windows, speech lines) is in
`variants/phrasing.py`.

## Modules

| file | role |
|---|---|
| `contracts.py` | typed records exchanged between stages (`ShotCase`, `RenderRecord`, `ScoreRecord`, ...) |
| `cases.py` | build `ShotCase`s from Firestore REST dumps / plain JSON exports; `binding_mismatches` proves spec `IMAGE_REF_k` tokens match the images sent |
| `runner.py` | resumable thread-pooled renderer (`renders.jsonl`, `clips/`, `requests/`), cost estimate |
| `frames.py` | ffmpeg 3 fps frames, scene-score hard-cut detection, contact sheets |
| `frame_judge.py` | independent checklist judge over frames + free-text transcription + dialogue similarity |
| `scorer.py` | eval engine + frame checks per render (`scores.jsonl`, `evals/*.json`) |
| `report.py` | per-variant × per-dimension means, paired bootstrap deltas vs V1, per-case tables |

## Usage

```bash
cd productions_service
export GOOGLE_CLOUD_PROJECT=aug18-25-3   # Vertex, location global
W=/path/to/workdir                       # holds cases.json; outputs land here
python -m storygraph.experiments.prompt_ab prompts --cases $W/cases.json --out $W
python -m storygraph.experiments.prompt_ab render  --cases $W/cases.json --out $W \
    --samples 1 --extra-variants V1_json,V2_prose --workers 8   # <= 48 renders enforced
python -m storygraph.experiments.prompt_ab score   --cases $W/cases.json --out $W --workers 6
python -m storygraph.experiments.prompt_ab report  --cases $W/cases.json --out $W --report-md $W/report.md
```

`cases.json` is a list of `ShotCase.to_dict()` records; build them with
`cases.build_case(CaseSource(...))` from a project's `generation_runs`, `shots`, `assets`,
`entities` exports (pick the run whose compiled spec you want to test) and check
`binding_mismatches(case) == []` before rendering.

## Note on the transcriber

The experiment found that `adapters/transcribe.py` returned empty transcripts (optional
`segments` in the response schema → `gemini-3.8-flash` answered `{"available": true}`), so
the critic reported every scripted line missing. That is now fixed in the adapter; the
scorer still pins `GeminiTranscriber(model="gemini-3.1-pro-preview")` so v1 results are
reproducible.
