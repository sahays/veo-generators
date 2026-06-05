# Ask Aanya — Agent Tools & API Coverage

How the in-app chat assistant ("Ask Aanya") maps to backend APIs. Aanya is an
**orchestrator** that routes the user's intent to one of three **specialists**.
Every job-creating action is **propose → confirm**: a tool records a proposal that
renders a confirmation card; the job only runs when the user clicks **Confirm** (the
frontend then calls the create endpoint directly).

- Backend agents: `api/agents/factory.py` (orchestrator), `api/agents/specialists/*`, shared helpers in `api/agents/_shared.py`, tool→API wrappers in `api/agents/tools/*`.
- Chat endpoint: `POST /api/v1/chat` (`api/routers/chat.py`). Tools reach the API in-process via `agents/tools/_client.py`.
- Frontend widgets: `frontend/src/components/chat/ChatWidgets.tsx`, wired in `ChatWindow.tsx`.

---

## Orchestrator — Aanya (routing)

Routes the user's intent to the right specialist and relays its response:

- New projects / scripts / system prompts → **director**
- Reframe / key moments / thumbnails → **editor**
- Promos / adapts → **marketer**

> Pricing/costing tools are intentionally omitted from this doc.

---

## Workflows — who calls what

**Routing.** Every message enters through Aanya, which delegates to one specialist:

```
  User
   │  "make a thumbnail from production X" / "create a 16:9 ad" / "adapt this image"
   ▼
  Aanya  (orchestrator, POST /api/v1/chat)
   │  routes by intent
   ├──▶ Director   productions · system prompts
   ├──▶ Editor     reframe · key moments · thumbnails
   └──▶ Marketer   promos · adapts
```

**The common shape.** Specialists never run a job directly. They gather inputs via
pickers, then emit a proposal; the user confirms; the frontend calls the create endpoint:

```
  specialist ──▶ open picker(s)         (source, prompt, options)
             ──▶ resolve source ref → gs://   (else re-open the picker)
             ──▶ propose_*()  ──▶  ConfirmationCard
                                        │  user clicks Confirm
                                        ▼
                          frontend POSTs the create endpoint
```

### Thumbnails (Editor) — full path incl. the page handoff

```
 User: "make a thumbnail from production X"
   └─▶ Aanya ─▶ Editor
        1. list_available_videos()   ─▶ VideoSourcePicker
             GET /promo/sources/uploads + /promo/sources/productions
           user picks ─▶ "Use production X (URI: gs://…)"
        2. list_thumbnail_prompts()  ─▶ PromptPicker
             GET /system/resources?type=prompt&category=thumbnails
           user picks ─▶ "Use prompt … (ID: res-…)"
        3. propose_thumbnails(gcs_uri, prompt_id)
             └─ resolve_source_uri(video) → gs://…   └─ ConfirmationCard
        4. Confirm ─▶ POST /api/v1/thumbnails/analyze        (frame metadata)
        5. result "View" ─▶ /thumbnails/{id}  (page auto-captures frames)
             ─▶ pick collage prompt ─▶ POST /api/v1/thumbnails/{id}/collage
```

### Key moments (Editor)

```
 Aanya ─▶ Editor
   list_available_videos()       ─▶ VideoSourcePicker
   list_key_moment_prompts()     ─▶ PromptPicker  (category=key-moments)
   propose_key_moments(gcs_uri, prompt_id)
        └─ resolve_source_uri(video) → ConfirmationCard
   Confirm ─▶ POST /api/v1/key-moments/analyze
```

### Reframe (Editor)

```
 Aanya ─▶ Editor
   list_available_videos()  ─▶ VideoSourcePicker
   list_content_types()     ─▶ text list   (content type chosen on the card)
   propose_reframe(gcs_uri, content_type)
        └─ resolve_source_uri(video) → ConfirmationCard
   Confirm ─▶ POST /api/v1/reframe
```

### Promo (Marketer) — video source

```
 Aanya ─▶ Marketer
   list_available_videos()  ─▶ VideoSourcePicker
   propose_promo(gcs_uri, target_duration, …)
        └─ resolve_source_uri(video) → ConfirmationCard
   Confirm ─▶ POST /api/v1/promo
```

### Adapts (Marketer) — image source

```
 Aanya ─▶ Marketer
   list_available_images()  ─▶ ImageSourcePicker
        GET /api/v1/adapts/sources/uploads
   list_adapt_options()     ─▶ aspect ratios / preset bundles
        GET /system/lookups/aspect-ratios
   propose_adapts(gcs_uri, aspect_ratios)
        └─ resolve_source_uri(image) → ConfirmationCard
   Confirm ─▶ POST /api/v1/adapts
```

### Production (Director) — no media source

```
 Aanya ─▶ Director
   list_prompt_categories()     GET /system/lookups/prompt-categories
   list_prompts(category)   ─▶ PromptPicker
        GET /system/resources?type=prompt&category=…
   propose_production(name, base_concept, prompt_id?)
        └─ ConfirmationCard
   Confirm ─▶ POST /api/v1/productions
```

---

## Director (productions + system prompts)

| Tool | API | Description |
|------|-----|-------------|
| `list_recent_productions` | `GET /api/v1/productions` | Recent production projects. |
| `list_prompt_categories` | `GET /api/v1/system/lookups/prompt-categories` | Distinct prompt categories with example names. |
| `list_prompts` | `GET /api/v1/system/resources?type=prompt&category=…` | Prompts in a category; **opens the PromptPicker** widget. |
| `propose_production` | *(confirm →)* `POST /api/v1/productions` | Propose creating a production. |
| `check_job_status` | `GET /api/v1/{feature}/{id}` | Status of a specific job. |

---

## Editor (reframe · key moments · thumbnails)

| Tool | API | Description |
|------|-----|-------------|
| `list_recent_reframes` | `GET /api/v1/reframe` | Recent reframe jobs. |
| `list_recent_key_moments` | `GET /api/v1/key-moments` | Recent key-moments jobs. |
| `list_recent_thumbnails` | `GET /api/v1/thumbnails` | Recent thumbnail jobs. |
| `list_content_types` | `GET /api/v1/system/lookups/content-types` | Valid reframe content types (drives the strategy/prompt). |
| `list_key_moment_prompts` | `GET /api/v1/system/resources?type=prompt&category=key-moments` | Key-moments analysis prompts; **opens PromptPicker**. |
| `list_thumbnail_prompts` | `GET /api/v1/system/resources?type=prompt&category=thumbnails` | Thumbnail analysis prompts; **opens PromptPicker**. |
| `list_available_videos` | *(opens VideoSourcePicker)* | Lets the user pick a video source (uploads + productions). |
| `propose_reframe` | *(confirm →)* `POST /api/v1/reframe` | Propose a vertical reframe. |
| `propose_key_moments` | *(confirm →)* `POST /api/v1/key-moments/analyze` | Propose a key-moments analysis. |
| `propose_thumbnails` | *(confirm →)* `POST /api/v1/thumbnails/analyze` | Propose thumbnail **analysis** (frame extraction). |
| `check_job_status` | `GET /api/v1/{feature}/{id}` | Status of a specific job. |

> **Thumbnail handoff:** chat runs only the *analysis*. The final collage (`POST /api/v1/thumbnails/{id}/collage`) needs browser frame-capture, so the result links to the Thumbnails page, which auto-captures frames and generates the collage (prompt category `collage`).

---

## Marketer (promos · adapts)

| Tool | API | Description |
|------|-----|-------------|
| `list_recent_promos` | `GET /api/v1/promo` | Recent promo jobs. |
| `list_recent_adapts` | `GET /api/v1/adapts` | Recent adapt jobs. |
| `list_adapt_options` | `GET /api/v1/system/lookups/aspect-ratios` | Valid aspect ratios + preset bundles. |
| `list_available_videos` | *(opens VideoSourcePicker)* | Pick the **video** source for a promo. |
| `list_available_images` | *(opens ImageSourcePicker)* | Pick the **image** source for an adapt (adapts resize an image). |
| `propose_promo` | *(confirm →)* `POST /api/v1/promo` | Propose a promo/highlight reel from a video. |
| `propose_adapts` | *(confirm →)* `POST /api/v1/adapts` | Propose multi-ratio adapts from an image. |
| `check_job_status` | `GET /api/v1/{feature}/{id}` | Status of a specific job. |

---

## Shared mechanics

**Source resolution** (`_shared.resolve_source_uri`) — every `propose_*` that takes a
source resolves the user's reference (id / name / filename) to a real `gs://` URI before
proposing; if nothing matches it opens the correct picker instead of forwarding a bad value.

| Kind | Catalogs searched |
|------|-------------------|
| `video` (reframe, key moments, thumbnails, promo) | `GET /api/v1/thumbnails/sources/productions` + `GET /api/v1/promo/sources/uploads` |
| `image` (adapts) | `GET /api/v1/adapts/sources/uploads` |

**Picker widgets** (frontend) — surfaced via the request context returned in the chat response:

| Widget | Trigger (`data.*`) | Data source |
|--------|--------------------|-------------|
| `VideoSourcePicker` | `source_picker: true` | `GET /api/v1/promo/sources/uploads` + `GET /api/v1/promo/sources/productions` |
| `ImageSourcePicker` | `source_picker: "image"` | `GET /api/v1/adapts/sources/uploads` |
| `PromptPicker` | `prompt_picker: "<category>"` | `GET /api/v1/system/resources?type=prompt&category=…` |
| `ConfirmationCard` | `confirmation: {…}` | Calls the create endpoint on Confirm |

**Backend guards** — `POST /thumbnails/analyze`, `POST /key-moments/analyze`, and
`POST /adapts` reject a non-`gs://` `gcs_uri` with a clear `400` (so a stray id can never
reach the model/worker as a fake file).

---

## By feature

| Feature | Agent | Source (picker) | Prompt category | Create endpoint |
|---------|-------|-----------------|-----------------|-----------------|
| Production | Director | — | browse via `list_prompt_categories`/`list_prompts` | `POST /api/v1/productions` |
| Reframe | Editor | Video (VideoSourcePicker) | — (content type drives it) | `POST /api/v1/reframe` |
| Key Moments | Editor | Video | `key-moments` | `POST /api/v1/key-moments/analyze` |
| Thumbnails | Editor | Video | `thumbnails` (analysis), `collage` on page | `POST /api/v1/thumbnails/analyze` → page collage |
| Promo | Marketer | Video | default | `POST /api/v1/promo` |
| Adapts | Marketer | **Image** (ImageSourcePicker) | — (ratios/presets) | `POST /api/v1/adapts` |
| **Avatars** | — | *not exposed in Ask Aanya* | — | — |
