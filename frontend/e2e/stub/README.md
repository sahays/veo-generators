# Stub API + browser harness

Renders the app in a real browser against fixture data: no Google Cloud, no
FastAPI backend. Everything lives in `frontend/e2e/stub/`; nothing under `src/`
imports it, so none of it reaches the production bundle.

All commands run from `frontend/`.

## Quick start

```bash
bash e2e/stub/make-media.sh                                   # once: video + filmstrip
npx playwright test -c e2e/stub/playwright.stub.config.ts     # starts both servers, runs the specs
```

Screenshots land in `e2e/stub/screenshots/`, traces of failed tests in
`e2e/stub/test-results/` (both ignored by git, as is `.media/`).

## The pieces

### 1. Media: `make-media.sh`

Writes `e2e/stub/.media/` using the system `ffmpeg` (libx264, drawtext) and `node`:

| File | What |
|---|---|
| `ad-spot.mp4` | 45.0 s, 640x360, 25 fps, H.264 yuv420p + AAC (quiet 220 Hz tone), faststart, a keyframe every second |
| `filmstrip.jpg` | 1600x450 sprite: 10 columns x 5 rows of 160x90 tiles, row-major, tile `i` = the frame at exactly `i` s (tiles 45-49 are black) |

Each of the nine fixture segments has its own background colour
(`data/palette.ts`) and burned-in `SEG n of 9`, title and time range. Every
frame also shows a running timecode and a white bar that sweeps left to right
over the 45 s, so a screenshot proves which time the player is showing. The
segment table comes from the fixture timeline (`tools/filtergraph.ts`), so the
video cannot drift from it.

The script is idempotent: outputs newer than their inputs are kept
(`--force` rebuilds). Without `drawtext` or DejaVu fonts it falls back to
colours + sweep bar and says so. Override the binaries with `FFMPEG=` / `FFPROBE=`.

### 2. Stub server: `server.ts`

```bash
node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON e2e/stub/server.ts
```

Node 22.18+ runs the TypeScript directly (native type stripping, no flag and
no build). The `--disable-warning` flag only silences a one-line notice about
`package.json` having no `"type"`; plain `node e2e/stub/server.ts` works too.
Listens on `127.0.0.1:8787` (`STUB_PORT` to change), logs one JSON line per
request to stdout, and logs unknown routes at level `warn` (`"what":"unknown_route"`)
so gaps are easy to spot. If the media is missing it still starts and says how to
generate it.

### 3. The app against the stub

```bash
FASTAPI_INTERNAL_ORIGIN=http://127.0.0.1:8787 \
AGENTS_SERVICE_ORIGIN=http://127.0.0.1:8787 \
PRODUCTIONS_SERVICE_ORIGIN=http://127.0.0.1:8787 \
NEXT_TELEMETRY_DISABLED=1 \
npx next dev --hostname 127.0.0.1 --port 5199
```

Open <http://127.0.0.1:5199/scene-analysis> and enter any invite code (the stub
accepts all of them as master). All three origins are pinned so that no Server
Action request can reach a real service.

### 4. Playwright: `playwright.stub.config.ts`

```bash
npx playwright test -c e2e/stub/playwright.stub.config.ts
npx playwright test -c e2e/stub/playwright.stub.config.ts scene-analysis   # one spec
```

- Separate from `frontend/playwright.config.ts`; picks up `e2e/stub/**/*.stub.spec.ts` only.
- Starts the stub and `next dev` itself, or reuses them if they are already
  listening (`reuseExistingServer`), which makes reruns much faster. Servers it
  started are stopped when the run ends.
- Uses the system Google Chrome (`channel: 'chrome'`, headless, 1440x900).
  Playwright's own browsers are not needed; do not run `npx playwright install`.
  If Chrome is somewhere unusual, set `STUB_CHROME_PATH=/path/to/chrome`.
- One worker: tests share the stub's in-memory state.
- `retries: 0`. Earlier runs saw `next dev` answer 500 (`Unexpected end of JSON input`)
  mid-test. The cause was Tailwind treating every file Playwright wrote under `e2e/`
  (screenshots, traces) as a source change and recompiling; `src/index.css` now has
  `@source not "../e2e"`, and a full run triggers no recompiles. Editing files under
  `src/` while a run is in progress can still cause a 500.
- `console.error` output of a page (React warnings included) does not fail a
  test. It is printed as a `[stub-e2e]` line under the test and attached to the
  report as `console-errors.txt`.

Specs:

| File | Checks |
|---|---|
| `scene-analysis.stub.spec.ts` | Landing lists the three seeded records; create page lists the stub uploads and productions; starting an analysis from an upload lands on `/scene-analysis/sa-stub-1`; the workspace of `sa-fixture-ad-spot` loads without a crash (minimal on purpose) |
| `scene-workspace.stub.spec.ts` | Scene Analysis workspace: aligned lanes, seek, zoom and pan, tabs, pins, lane toggles, keyboard, deep links, export, job progress, light theme |
| `media.stub.spec.ts` | The browser decodes the stub video, seeks backwards and forwards over Range requests, and the frame's colour matches the segment at that time |
| `engagement.stub.spec.ts` | Landing lists the six seeded reports with status, signal badge, duration and headline; create from an analysed video and a template; `?analysis=` preselection (and an unknown id); create from another video with an uploaded BARC file (progress, preview, mapping, offset, the request that was sent); a CSV whose columns cannot be mapped, and a file that is not a CSV |
| `engagement-workspace.stub.spec.ts` | Completed reports: header and honest labelling; every lane and the minimap on one scale; the recharts curve against the ruler and the marker lane (chart surface = plot box, chart-drawn dots at known times within 0.75 px of the ruler's x, also after a zoom); click and drag on the curve scrub without pausing and playback does not touch the curve's DOM; peak card seeks, zooms and selects, nearest card follows the playhead; driver selection shading and the Drivers lane; range inspector (Shift-drag on ruler and curve, a clicked segment) with the average recomputed sample by sample; BARC metric toggles and true values in the hover card; Data tab mapping, offset and windowed table; tabs, evidence chips, segment fixes; the four exports; `?t=` / `?sel=` deep link; keyboard |
| `engagement-states.stub.spec.ts` | Running job (stepper, then the workspace), job waiting on its scene analysis (note, link, start once the analysis is done), failed job with Retry, completed report without prose (empty states, no blank cards), light-theme screenshots of every main state, narrow window |

Helpers shared by the specs: `timelineHelpers.ts` (video state, visible range,
pointer positions on the time scale, `clientRect` for SVG shapes, downloads)
and `engagementSpecData.ts` (the report fixtures the stub serves, plus a
sample-by-sample reference for averages). Spec files are loaded by Playwright
as CommonJS: use `__dirname`, not `import.meta`, and do not import
`data/engagement/documents.ts` (it uses `import.meta.url`).

Write specs with the fixtures in `fixtures.ts`:

```ts
import { expect, test } from './fixtures.ts'

test('example', async ({ page, stub, shot, expectNoCrash }) => {
  await page.goto('/scene-analysis/sa-fixture-running')
  await stub.advanceSceneAnalysis('sa-fixture-running', 7) // jump to completed
  await expectNoCrash()                                    // no uncaught error, no Next error overlay
  await shot('my-page')                                    // e2e/stub/screenshots/my-page.png
})
```

Every test starts authenticated (`localStorage['veo-auth']` is seeded before
page scripts run) and with the stub reset to its seed state.

## Seeded scene analyses

| id | Starts as | Behaviour |
|---|---|---|
| `sa-fixture-ad-spot` | `completed` | The `AD_SPOT_RECORD` / `AD_SPOT_TIMELINE` fixture ("Kadak Chai — Monsoon (45s)"). |
| `sa-fixture-running` | `pending` | Moves one step on every `GET /scene-analysis/{id}` (see below). |
| `sa-fixture-failed` | `failed`, stage `analyze`, with an `error_message` | `POST .../retry` requeues it; it then runs like the one above. |
| `sa-stub-1`, `sa-stub-2`, ... | `pending` | Records created with `POST /scene-analysis`, or queued by `POST /engagement` for a video that has no live analysis; run like `sa-fixture-running`. |

A job in flight returns its current state and then moves one step, so a polling
page sees this sequence and is `completed` on the 8th poll:

| Poll | status | stage | stage_detail | progress_pct |
|---|---|---|---|---|
| 1 | `pending` | (empty, as the real backend leaves it) | | 0 |
| 2 | `analyzing` | `probe` | Reading the video and detecting cuts | 5 |
| 3 | `analyzing` | `analyze` | window 1 of 3 | 25 |
| 4 | `analyzing` | `analyze` | window 2 of 3 | 45 |
| 5 | `analyzing` | `analyze` | window 3 of 3 | 70 |
| 6 | `processing` | `merge` | Merging 3 windows | 85 |
| 7 | `processing` | `filmstrip` | Building the filmstrip | 95 |
| 8 | `completed` | `completed` | | 100 |

Only `GET /scene-analysis/{id}` moves a job; the list and the timeline routes do
not. (One exception: polling an engagement job that waits on a scene analysis
also moves that analysis, see below.) In dev, React StrictMode runs effects twice, so a page may consume two
steps on mount. Every job that completes serves the same fixture timeline, and
every record's `video_signed_url` is `http://127.0.0.1:8787/media/ad-spot.mp4`.

## Seeded engagement jobs

All on the ad-spot video (`sa-fixture-ad-spot`) unless noted. Records live in
`engagementState.ts`.

| id | Starts as | Signal | Behaviour |
|---|---|---|---|
| `eng-fixture-template` | `completed` | template `jumpy` | Serves `reports/template-jumpy.json`: 13 moments, with prose. "Monsoon spot — Jumpy template" |
| `eng-fixture-barc` | `completed` | BARC CSV `upl-fixture-barc-csv`, `Start Time` / `TVR (%)`, offset -5 s | Serves `reports/barc.json`: three metrics, 8 moments, with prose. `stage_detail` carries the parser's note about the 10 lead-in rows. "Monsoon spot — BARC ratings" |
| `eng-fixture-no-prose` | `completed` | template `jumpy` | Serves `reports/template-jumpy-no-prose.json`: same numbers, no prose; `headline` is empty and `stage_detail` is `Explanations could not be generated; Recommendations could not be generated`. "Monsoon spot — numbers only" |
| `eng-fixture-failed` | `failed`, stage `signal`, with an `error_message` | BARC CSV that is no longer in Files | `POST .../retry` requeues it; it then runs to `completed` and serves `reports/barc.json`. "Monsoon spot — missing CSV" |
| `eng-fixture-waiting` | `pending`, stage `waiting` | template `high` | Linked to `sa-fixture-running` (the trailer); waits for it, then runs. "Monsoon drama trailer — engagement" |
| `eng-fixture-running` | `pending` | template `slow_burn` | Moves one step on every `GET /engagement/{id}`. "Monsoon spot — in progress" |
| `eng-stub-1`, `eng-stub-2`, ... | `pending` | as created | Records created with `POST /engagement`. |

In the list they appear newest first: running, waiting, failed, no-prose, barc, template.

A job whose scene analysis is `completed` returns its current state and then
moves one step, so a polling page sees this sequence and is `completed` on the
6th poll. Stage names, details and progress values are the real worker's
(`workers/insight_jobs/engagement_processor.py`):

| Poll | status | stage | stage_detail | progress_pct |
|---|---|---|---|---|
| 1 | `pending` | (empty) | | 0 |
| 2 | `processing` | `signal` | `45 samples` (`90 samples` for BARC) | 15 |
| 3 | `processing` | `stats` | `13 moments found` | 30 |
| 4 | `processing` | `explain` | `Explaining 13 moments` | 34 |
| 5 | `processing` | `recommend` | `Writing recommendations` | 73 |
| 6 | `completed` | (empty, as the real worker leaves it) | notes joined with `; `, usually empty | 100 |

The number of moments is the number of extrema in the report the job serves:
jumpy 13, BARC 8, low 7, high 6, front_loaded 2, slow_burn 1. `duration_sec` is
set from the `stats` step on; `headline`, `kpis`, `usage` and `completedAt` on
completion.

**Waiting on a scene analysis.** While the linked scene analysis is not
`completed`, the job stays `pending` / `waiting` / `Waiting for scene analysis`
and does not move through its own stages. Each `GET /engagement/{id}` of a
waiting job also moves that scene analysis one step (as if the scene worker
were running), so in a manual demo the job finishes by itself: 7 waiting polls
for a fresh analysis, then the six polls above. When the analysis is
`completed` the job starts at poll 1 of the table. When it can never complete
(deleted, `failed`, or archived before it finished) the job becomes `failed`
with the worker's message, `stage` empty and `progress_pct` 0. `GET /engagement`
(the list), `/report` and plain reads never move anything.

**Which report a completed job serves.** A template job serves
`reports/template-<template_id>.json`; every BARC job serves `reports/barc.json`,
whatever CSV, time column, metric or offset it was created with (the stub never
parses uploaded bytes). Only `template-jumpy` and `barc` have prose. A job that
completes with one of the other templates therefore looks like a job whose
language-model steps failed: empty `headline`, no titles or recommendations,
and the two "could not be generated" notes in `stage_detail`.

In specs, `stub.advanceEngagement(id, steps)` moves a job without polling
(`POST /__stub/engagement/{id}/advance`). It never touches the scene analysis:
a waiting job stays waiting until `stub.advanceSceneAnalysis(...)` has completed
its analysis, and then starts and moves by `steps`.

## Routes

Under `/api/v1` unless noted. Status codes and bodies follow the FastAPI routers.

| Route | Notes |
|---|---|
| `POST /auth/validate` | Any code: `{valid, is_master, is_power}` all true |
| `GET /models`, `/models/defaults`, `/models/regions` | Text model `gemini-3.8-flash` |
| `GET /pricing/features` | Every feature bills the text model |
| `GET /pricing/usage/{feature}/{id}` | `FeaturePricing` with one Gemini token line from the record's `usage`; 400 unknown feature, 404 unknown record |
| `GET /uploads` (`?file_type=`), `GET /uploads/{id}` | Three videos and one CSV (`barc-kadak-chai-monsoon.csv`), plus files uploaded through the upload flow (newest first) |
| `POST /assets/upload/init`, `POST /assets/upload/complete` | The direct-upload flow, see "Upload flow" |
| `GET /scene-analysis` (`?archived=true`) | Newest first |
| `POST /scene-analysis` | `SceneAnalysisCreate` → `{id, status: 'pending'}`; 422 `{detail: [{loc, msg, type}]}` on invalid or extra fields, 404 unknown source |
| `GET /scene-analysis/sources/uploads`, `/sources/productions` | `UploadItem[]`, `ProductionItem[]` |
| `GET` / `PATCH` / `DELETE /scene-analysis/{id}` | PATCH accepts `display_name` |
| `POST /scene-analysis/{id}/archive`, `/unarchive`, `/retry` | Retry is 400 for a `pending` or `completed` record |
| `GET /scene-analysis/{id}/timeline` | `TimelineResponse`; 409 `{detail}` unless completed |
| `GET /engagement` (`?archived=true`) | Newest first |
| `POST /engagement` | `EngagementCreate` → `{id, status: 'pending', scene_analysis_id}`. 422 for shape problems (extra keys, wrong types, too-long strings; `loc` is `["body", "signal", "<field>"]` inside `signal`). 400 `{detail}` for the rules: exactly one of `scene_analysis_id` or `source_type` + `source_id`; a template needs a known `template_id`; BARC needs `upload_id`; `offset_sec` within 86400 s of zero; the chosen analysis must not be archived or failed. 404 for an unknown analysis, source or signal file. With a source, the newest live analysis of that source is reused, else a new `pending` scene analysis (`sa-stub-N`) is queued |
| `GET /engagement/sources/uploads`, `/sources/productions` | As for scene analysis |
| `GET /engagement/sources/analyses` | Non-archived scene analyses, newest first: `{id, display_name, video_filename, source_type, source_id, status, duration_sec, createdAt, video_signed_url}` |
| `GET /engagement/templates` | `EngagementTemplate[]`: `high`, `low`, `jumpy`, `slow_burn`, `front_loaded` |
| `POST /engagement/signal-preview` | `{upload_id}` → `SignalPreview`. 404 unknown upload; 400 when the upload is not finished or is not a CSV (extension `.csv` / `.tsv` / `.txt` or a text MIME type). The preview is picked by filename: a name listed in `data/engagement/previews.json` (`barc-kadak-chai-monsoon.csv`, `unmappable-notes.csv`) gets its own preview, any other CSV gets the BARC preview with `filename` replaced |
| `GET` / `PATCH` / `DELETE /engagement/{id}` | `GET` is the polling endpoint. PATCH accepts `display_name` |
| `POST /engagement/{id}/archive`, `/unarchive`, `/retry` | Retry is 400 for a `pending` or `completed` record |
| `GET /engagement/{id}/report` | `EngagementReport`; 409 `{detail: "Engagement report is not ready"}` unless completed |
| `GET /media/{file}` (no prefix) | Range / 206 / 416, `Accept-Ranges`, CORS `*`; only files in `.media/` |
| `POST /__stub/reset` (no prefix) | Restore the seed state |
| `POST /__stub/scene-analysis/{id}/advance` (no prefix) | Body `{"steps": n}` (default 1): move a job without polling |
| `POST /__stub/engagement/{id}/advance` (no prefix) | The same for an engagement job (1 to 20 steps); a job waiting on its scene analysis stays waiting |
| `PUT /__stub/upload/{record_id}` (no prefix) | Where the browser sends the file bytes during an upload; CORS `*`, 12 MB cap |
| `GET /__stub/health` (no prefix) | `{status, missing_media}` |
| anything else | 404 `{detail}` and a `warn` log line |

## Upload flow

The create page uploads a BARC CSV with `api.assets.directUpload`, which on the
real backend talks to GCS. The stub plays both parts (`routes/uploads.ts`):

1. `POST /api/v1/assets/upload/init` `{filename, content_type, file_size_bytes}`
   → `{record_id, upload_url, gcs_uri, content_type, expires_at}`. The record is
   `upl-stub-1`, `upl-stub-2`, ... and `pending`; `upload_url` is
   `http://127.0.0.1:8787/__stub/upload/{record_id}`.
2. The browser sends `PUT {upload_url}` with the bytes. The request is
   cross-origin (app on 5199, stub on 8787), so the stub answers the preflight
   and the PUT with `Access-Control-Allow-Origin: *`. The bytes are counted and
   thrown away; more than 12 MB is a 413.
3. `POST /api/v1/assets/upload/complete` `{record_id}` → `{id, gcs_uri, signed_url, file_type}`
   and the record is `completed`. 404 for an unknown record, 400
   `File not found in GCS` when the bytes never arrived. `signed_url` is the
   fixture video for a video upload and empty for anything else.

A completed upload is visible to `GET /uploads`, `GET /uploads/{id}`,
`POST /engagement/signal-preview` and `POST /engagement` (as `signal.upload_id`).
It is not offered as a video source (`/sources/uploads` lists the catalog
videos only). `POST /__stub/reset` drops every uploaded record.

## Engagement fixtures

`data/engagement/` holds the documents the Engagement routes serve. Everything
with a number in it is generated by the real engagement maths
(`api/engagement_signals`, the code the worker runs) from the ad-spot timeline:

```bash
# from the repository root; needs node and the API virtualenv, no network
api/venv/bin/python frontend/e2e/stub/data/engagement/generate_fixtures.py
```

| File | What | Edited by |
|---|---|---|
| `barc-kadak-chai-monsoon.csv` | Input. BARC export layout, one row per half second: 100 rows from 20:14:55.0, the first 10 before the spot starts (hence offset -5 s). TVR, impressions, reach | hand |
| `unmappable-notes.csv` | Input. Text columns only, so the preview reports that no time column was found | hand |
| `prose.json` | Input. What the language model would have written for `template-jumpy` and `barc`: a title, explanation and drivers per moment, and the recommendations | hand |
| `templates.json` | `list_templates()` | generator |
| `previews.json` | `preview_signal_csv` of both CSVs | generator |
| `signal-notes.json` | Parser warnings the worker would note on a BARC job's record | generator |
| `reports/template-<id>.json` | One report per template. The curve is seeded with the id of the seeded record that uses the template (`eng-stub` for `low` and `front_loaded`) | generator |
| `reports/template-jumpy-no-prose.json` | The jumpy report before the prose is bound | generator |
| `reports/barc.json` | The report of the BARC CSV. With 90 samples its `smoothed` curve differs from the raw TVR points; the template reports have 45 samples, where smoothing is a no-op | generator |

The generator prints a digest of every report (moments, influence, weakest
segments). Read it before touching `prose.json`: the prose has to describe the
numbers. The run exits non-zero, and writes nothing, when the prose cites a
moment id, influence key or segment id that the report does not have, cites an
influence entry the recommendation prompt would not offer (low support, or the
wrong sign), or leaves a moment without a title and explanation. So a change in
the maths that renumbers the moments cannot silently strip prose from a
fixture. Output is byte-identical from run to run. `documents.ts` loads the
JSON once when the stub starts: restart the stub after regenerating.

## Adding a feature

Scene Analysis and Engagement are both implemented; use them as the pattern for
the next one. `routes/sceneAnalysis.ts` + `state.ts` is the smaller example,
`routes/engagement.ts` + `engagementState.ts` + `data/engagement/` shows a job
that depends on another feature's records and serves generated documents.

1. **State and fixtures.** Keep records in a store shaped like `state.ts`
   (a `Map` by id, a seed, `reset()`), and static documents under `data/`.
   Generate documents from the real backend code where there is any (see
   "Engagement fixtures") instead of writing numbers by hand.
2. **Routes.** Export a `StubFeature` from `routes/<feature>.ts` and add it to
   `FEATURES` in `routes/index.ts`:

   ```ts
   const BASE = '/api/v1/engagement'
   const routes: Route[] = [
     ...sourceRoutes(BASE),                                  // /sources/uploads, /sources/productions
     route('GET', `${BASE}/templates`, () => ok(TEMPLATES)),
     route('GET', `${BASE}/{id}/report`, (ctx) => {
       const record = store.get(ctx.params.id)
       if (!record) throw new HttpError(404, 'Engagement report not found')
       if (record.status !== 'completed') throw new HttpError(409, 'Engagement report is not ready')
       return ok(store.report(ctx.params.id))
     }),
   ]
   ```

   `{name}` segments are parameters. Literal segments always win over
   parameters, whatever the registration order, so `/templates` is never
   shadowed by `/{id}`. A duplicate method + path fails at startup.
3. **Helpers.** `ctx.body()` (parsed JSON object), `ctx.query`, `ctx.mediaUrl(file)`,
   `BodyFields` in `lib/validate.ts` for 422s (see `underSignal` in
   `routes/engagement.ts` for a nested object), `lookupUpload` in
   `routes/uploads.ts`, and `sceneAnalysisStore` from `state.ts` to link scene
   analyses. Take status codes and `{detail}` texts from the real router.
4. **Feature object.** Set `reset` (called by `POST /__stub/reset`, in
   `FEATURES` order, so list a feature after the ones its seed links to) and
   `usage` (feeds `GET /pricing/usage/<feature>/{id}`).
5. **Playwright control.** If jobs move on polls, add a
   `POST /__stub/<feature>/{id}/advance` route and a helper on `StubControl` in
   `fixtures.ts` (`advanceSceneAnalysis`, `advanceEngagement`).
6. Restart the stub: it has no watch mode.

The rules for these files: erasable TypeScript only (no enums, namespaces or
parameter properties), `import type` for types, and explicit `.ts` import
specifiers. Check with `npx tsc -p e2e/stub/tsconfig.json`.

## Layout

```
server.ts                    HTTP server: parse, dispatch, log
ports.ts                     ports and origins shared by server, config and fixtures
state.ts                     scene analysis records, seed, progression
engagementState.ts           engagement records, seed, progression, waiting on a scene analysis
media.ts                     /media/{file} with Range support
lib/                         router (trie), http helpers, validation, logger, feature contract
routes/                      index (route table), core, sceneAnalysis, sources, engagement, uploads
data/                        models, pricing, uploads, productions, segment palette
data/engagement/             engagement reports, templates, previews: generator, its inputs and outputs
tools/filtergraph.ts         ffmpeg filter graph, derived from the fixture
make-media.sh                media generator
playwright.stub.config.ts    Playwright config (system Chrome, both web servers)
fixtures.ts                  Playwright fixtures: auth seed, stub reset, screenshots
timelineHelpers.ts           page helpers shared by the workspace specs
engagementSpecData.ts        engagement report fixtures and reference maths for the specs
*.stub.spec.ts               specs
```
