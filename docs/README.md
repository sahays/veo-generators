# VeoGen

AI-powered video production platform built on Google Veo and Gemini.

> **Problem:** Creating professional video ads requires expensive tools, specialized skills, and hours of manual editing.
> **Solution:** VeoGen automates the entire pipeline — from script to final cut — using AI models for generation, reframing, and compositing.

> **Architecture:** FastAPI backend orchestrates Gemini (script/storyboard) and Veo (video generation) on Cloud Run, with a React frontend and Firestore for state. A dedicated worker service handles long-running renders asynchronously via a polling loop.

---

## Productions

Create AI-generated video ads from a text prompt. Choose a production type (Movie, Ad, Promo), describe your concept, configure director style and camera movement, and VeoGen generates a storyboard and renders the final video.

[List](#productions-list) · [Create](#productions-create) · [Detail](#productions-detail) · [Script Editor](#productions-script)

### Productions List
![](productions.png)

### Productions Create
Sections: Production Type, Concept & Vision, System Configuration, Duration, Orientation, Visual Reference
![](productions-create.png)

### Productions Detail

**Video Player & Header** — title, status badge, generation date, resource usage sidebar
![](productions-detail-hero.png)

**[Production Brief](#production-brief)** — base concept, format, duration, scene count, analysis prompt
![](productions-detail-brief.png)

**[Final Storyboard](#final-storyboard)** — scene thumbnails with timestamps and descriptions
![](productions-detail-storyboard.png)

### Productions Script
Scene cards with visual descriptions, audio controls (voice-over, music), frame/video generation status. Supports grid and list layout modes.
![](productions-script.png)

---

## Key Moments

Extract highlight clips from existing videos. Upload a video and Gemini analyzes it to identify the most impactful moments, returning timestamped segments with a video summary.

[List](#key-moments-list) · [Create](#key-moments-create) · [Detail](#key-moments-detail)

### Key Moments List
![](key-moments.png)

### Key Moments Create
Select a video source from Productions or Files, then run AI analysis.
![](key-moments-create.png)

### Key Moments Detail

**[Video Summary](#video-summary)** — AI-generated summary of the full video
![](key-moments-detail-summary.png)

**[Key Moments Grid](#key-moments-list)** — timestamped moments with descriptions, tags, and relevance scores
![](key-moments-detail-moments.png)

---

## Thumbnails

Generate eye-catching thumbnails for your videos. Gemini's image model captures key frames, then composites them into a collage thumbnail.

[List](#thumbnails-list) · [Create](#thumbnails-create) · [Detail](#thumbnails-detail)

### Thumbnails List
![](thumbnails.png)

### Thumbnails Create
Select a video, identify key moments, then generate a collage thumbnail.
![](thumbnails-create.png)

### Thumbnails Detail

**[Screenshots](#screenshots)** — captured key frames with descriptions
![](thumbnails-detail.png)

**[Generated Thumbnail](#generated-thumbnail)** — final collage output
![](thumbnails-detail-result.png)

---

## Files

Upload and manage source videos and assets. Drag-and-drop files that can be used across productions, key moments, orientations, and promos.

[List](#files-list) · [Detail](#files-detail)

### Files List
![](uploads.png)

### Files Detail
Video player, editable display name, file metadata (MIME type, size, upload date, source), compressed variants.
![](uploads-detail.png)

---

## Orientations

Reframe videos for different aspect ratios (16:9 to 9:16). The reframer intelligently crops and repositions content so a landscape ad works on Stories or Reels without manual re-editing.

[List](#orientations-list) · [Create](#orientations-create) · [Detail](#orientations-detail)

### Orientations List
![](orientations.png)

### Orientations Create
Select a landscape video, choose reframe options, and configure the analysis prompt.
![](orientations-create.png)

### Orientations Detail
**[Original (16:9)](#original-video)** side-by-side with **[Reframed (9:16)](#reframed-video)**, download button, cost breakdown.
![](orientations-detail.png)

---

## Promos

Stitch together clips into short promotional videos. Select source videos, define target duration, and VeoGen assembles a final promo with title cards and parallel FFmpeg encoding.

[List](#promos-list) · [Create](#promos-create) · [Detail](#promos-detail)

### Promos List
![](promos.png)

### Promos Create
Select a video source, configure the promo prompt, and set target duration.
![](promos-create.png)

### Promos Detail

**[Promo Output](#promo-output)** — rendered promo video with download
![](promos-detail-output.png)

**[Title Card](#title-card)** — generated collage title card
![](promos-detail-titlecard.png)

**[Selected Moments](#selected-moments)** — extracted segments with timestamps and descriptions
![](promos-detail-moments.png)

---

## System Prompts

View and manage the AI prompt templates that drive each generation step. Master users can create and edit prompts; regular users can browse them to understand how the AI is instructed.

[List](#system-prompts-list) · [Detail](#system-prompts-detail)

### System Prompts List
![](system-prompts.png)

### System Prompts Detail
Full prompt content with metadata (category, version, active status).
![](system-prompts-detail.png)
