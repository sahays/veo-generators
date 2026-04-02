# VeoGen

AI-powered video production platform built on Google Veo and Gemini.

> **Problem:** Creating professional video ads requires expensive tools, specialized skills, and hours of manual editing.
> **Solution:** VeoGen automates the entire pipeline — from script to final cut — using AI models for generation, reframing, and compositing.

> **Architecture:** FastAPI backend orchestrates Gemini (script/storyboard) and Veo (video generation) on Cloud Run, with a React frontend and Firestore for state. A dedicated worker service handles long-running renders asynchronously via a polling loop.

![Login](login.png)

---

## Productions

Create AI-generated video ads from a text prompt. Choose a production type (Movie, Ad, Promo), describe your concept, configure director style and camera movement, and VeoGen generates a storyboard and renders the final video.

| | |
|---|---|
| ![Productions](productions.png) | ![New Production](new-production.png) |

---

## Key Moments

Extract highlight clips from existing videos. Upload a video and Gemini analyzes it to identify the most impactful moments, returning timestamped segments you can export as standalone clips.

![Key Moments](key-moments.png)

---

## Thumbnails

Generate eye-catching thumbnails for your videos. Gemini's image model creates multiple thumbnail options from a video or prompt, so you can pick the best one without opening a design tool.

![Thumbnails](thumbnails.png)

---

## Files

Upload and manage source videos and assets. Drag-and-drop files that can be used across productions, key moments, orientations, and promos.

![Files](uploads.png)

---

## Orientations

Reframe videos for different aspect ratios (16:9, 9:16, 1:1). Powered by FFmpeg, the reframer intelligently crops and repositions content so a landscape ad works on Stories or Reels without manual re-editing.

![Orientations](orientations.png)

---

## Promos

Stitch together clips into short promotional videos. Select source videos, define the cut order and length, and VeoGen assembles a final promo with parallel FFmpeg encoding.

![Promos](promos.png)

---

## System Prompts

View and manage the AI prompt templates that drive each generation step. Master users can create and edit prompts; regular users can browse them to understand how the AI is instructed.

![System Prompts](system-prompts.png)

---

## Diagnostics

Verify connectivity to all external services — GCS storage, Gemini script analysis, Imagen storyboard generation, and Veo video rendering. Each card runs a live health check and reports status.

![Diagnostics](diagnostics.png)

---

## Invite Codes

Control access to the platform. Master users create invite codes with daily credit limits and optional expiry dates, and can revoke or reactivate them at any time.

![Invite Codes](invite-codes.png)
