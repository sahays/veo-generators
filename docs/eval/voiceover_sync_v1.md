# Voiceover sync v1 — fixed character voices for Omni clips

**Q.** Omni invents a new voice per clip (it accepts no audio reference), so Pip and Ava
sound different from shot to shot. Can we keep Omni's picture/timing but re-voice every
scripted line with one fixed TTS voice per character?

## v5 — stem-based audio (`audio.mode: stems`) — **new default**

Omni always renders audio (there is no audio-off flag and no audio references), and it
lip-syncs only to speech it generates itself. So dialogue stays in the prompt, and Omni's
audio is used as a **guide track** only: it supplies the line timing (transcribe +
`align_lines`) and never reaches the final mix. Final clip = Omni picture + our stems:

- **Dialogue stem:** the fixed-voice TTS, placed on the guide timings (0.85× pace, atempo
  ≤ 1.35), over silence.
- **SFX stem:** demucs `htdemucs` `no_vocals` of the guide. Residual voice is ducked by
  −24 dB wherever the separated *vocals* stem is active (VAD on vocals, so SFX never
  trigger it) or the transcript places speech.
- **Music:** the S5 `MusicCue` bed in S10, sidechain-ducked under the **dialogue stem
  only** (a stitched dialogue key track), not under the SFX.
- **Mixer:** one typed `StemMix` contract (stem URIs, gains, LUFS targets: dialogue −16,
  SFX −24 with a +6 dB boost cap, music −26), rendered in S10. Stems are stored per
  `GenerationRun.stems`, so a remix never re-renders.
- **Prompt:** "No background music." added to the Omni negatives, so the guide track has
  no music to leak into the SFX stem.

**SFX source decision (a/b/c).** Option (b), graph-driven SFX, needs a model that
generates foley. On aug18-25-3 the only Google audio-generation models are `lyria-002`
(Vertex predict) and `lyria-3-clip-preview` (Gemini API, AUDIO+TEXT). Both returned
**music** for the prompt "single brass key clink on a workbench": per the Gemini judge,
lyria-002 produced a 36 s trap beat and lyria-3 a 30 s ambient/electronic track, with no
clink in either. `gemini-*-tts` and native-audio Live are speech-only. So (b) and the
hybrid (c) are not feasible today, and **(a) demucs** is the SFX source.

### Results (same 6 p-0irbygdv clips; `exp_stems/` vs v4 `exp_v4/`)

| Metric | voiceover_duck (v4) | **stems (v5)** |
|---|---|---|
| Leftover Omni voice (Gemini listening) | 1/6 faint | **0/6** |
| Bed level outside speech vs original | −12 to −13.5 dB on 3/6, −3.5 dB on 1/6 | +4.9 to +6.2 dB on 5/6 (SFX brought up to −24 LUFS, boost capped); −8.2 dB on 1/6 (scn_003_02, demucs) |
| SFX present (judge) | 5/6 | 5/6 (scn_007_02's original bed is silent, −54 dB) |
| SFX sync to picture (judge, 0–1) | — | 0.85–0.95 on 5/6; cross-correlation lag −5 ms on 6/6 (< 1 frame) |
| Mix naturalness (judge, mean) | 0.79 | 0.76 (scn_007_02 0.35: dry, no bed; others 0.80–0.88) |
| Lines heard complete / median overrun | 7/7 / 0.0 s | 7/7 / 0.0 s |
| Same-voice: Pip / Ava (Omni → ours) | 0.33 → 1.0 / 0.65 → 1.0 | 0.35 → 1.0 / 0.40 → 1.0 |
| Latency per clip | 13–20 s | 22–36 s (demucs 8.3 s wall, 2.6 cores, 1.37 GB RSS; the rest is Gemini transcribe + TTS) |
| Productions image | 1.16 GB | **2.23 GB (+1.07 GB:** torch 2.14.1+cpu, torchaudio, demucs 4.1, htdemucs weights baked in) |
| Cloud Run fit | — | fits the productions service (4 vCPU / 8 GiB); ≈ 8 vCPU-s per clip, about $0.0002 |

**Decision:** stems beats voiceover_duck on SFX preservation and has zero leftover Omni
voice, so it is the default: `audio.mode: stems` (`config.py` and `default.yaml`).

**Caveats:**

- Demucs still drops part of the bed on some clips (scn_003_02).
- Clips whose guide has no bed (scn_007_02) sound dry. Graph-driven foley would fix this
  once a foley-capable model exists.
- `voiceover_duck` and `omni` remain available as fallbacks.

## v4 (TTS paced to 0.85× window, duck −26 dB over transcript ∪ VAD + 150 ms) — **`sync` on**

Changes from v3:

- TTS is asked to fit 0.85× Omni's speech window (`audio.pace_factor`).
- Ducking runs at −26 dB.
- The ducked windows add a speech-band (200–3800 Hz) energy VAD over Omni's original
  audio, so whispers the transcript misses are also ducked (`audio/voice/vad.py`).
- Windows are padded by 150 ms.

Results on the same 6 clips with `duck` (`exp_v4/`):

| Gate | Bar | v3 | **v4** |
|---|---|---|---|
| Median end overrun past Omni window | ≤ 0.4 s | 0.44 s | **0.0 s** (p90 1.30 s; 0, 0, 0, 0, 0.65, 1.30, 1.49) |
| Lines heard complete | 7/7 | 7/7 | **7/7** (min similarity 0.89) |
| Clips with residual Omni voice | ≤ 1/6 | 2/6 | **1/6** (scn_007_02, *faint*) |

Same-voice scores: Pip 0.33 → **1.0**; Ava 0.65 → **1.0**. In this sample Omni also gave
Ava a second voice. F0 spread: Ava 19 Hz, Pip 37 Hz; dropping delivery hints fixed Ava's
61 Hz.

**Decision:** the gate passed, so the default is now `audio.voiceover: sync` with
`speech_removal: duck`.

> [!WARNING]
> **SFX trade-off.** The VAD also catches loud in-band SFX/ambience. The bed level outside
> the transcript and TTS windows fell 12–13.5 dB on 3/6 clips (scn_001_01, scn_003_02,
> scn_007_01) and 3.5 dB on scn_004_02. The Gemini listener still reports SFX audible on
> all clips with a bed (mix naturalness 0.82–0.88). If SFX matter more, either raise the
> VAD margin or switch those clips to demucs.

The v2 and v3 analysis below is unchanged.

## v3 update (pace-to-window TTS, no delivery hints, `tempo_max` 1.35) — still `off`

Each line now asks Gemini TTS to "take about N seconds", where N is the length of Omni's
speech window. Delivery hints are dropped and `tempo_max` is raised to 1.35. Results from
re-running the 6 clips with `duck` (`exp_v3/`):

| Metric | v2 | v3 |
|---|---|---|
| Lines heard complete | 7/7 | **7/7** |
| End overrun past Omni window (median / p90) | ≈1.7 / ≈2.0 s | **0.44 / 1.38 s** (0, 0, 0, 0.44, 0.76, 1.38, 1.51) |
| Lines at the tempo cap | 6/7 | 4/7 |
| Pip same-voice (Omni → voiced) | 0.45 → 1.0 | 0.40 → 1.0 |
| Residual Omni voice with duck (Gemini listening) | 1/6 | **2/6** (scn_007_01 whisper; scn_007_02 "original dialogue under the voiceover") |

**Gate not met:** the bar was median ≤ 0.4 s with 7/7 intelligible. The median is 0.44 s,
and ducking left audible Omni speech on 2/6 clips. `audio.voiceover` stays `off`. Next
levers: a pace hint below the window (e.g. 0.85× window), a deeper duck (−24…−30 dB) or
duck wherever voice is detected, and selective demucs for clips with residual speech.

The v2 analysis below is unchanged.


**Answer.** Yes. The pipeline is built behind `audio.voiceover: off | sync` (default
**off**). On 6 clips from p-0irbygdv, Pip goes from 2 voices to 1, and every line stays
intelligible and complete. The one thing that blocks turning it on: Gemini TTS speaks
more slowly than Omni, so most lines run **1.5–2 s past the end of the lip movement**,
even at the maximum tempo (1.25×). Tuning options are listed at the end.

## What was built

| Piece | Where |
|---|---|
| Voice registry: archetype (robot/child/adult/elder × gender from attributes + story pronouns) → Gemini prebuilt voice, chosen by `sha256(entity_id)` rotation with no voice shared across the cast; stored on `Entity.voice`, never reassigned; `set_voice` for human edits | `audio/voice/{archetype,catalog,registry}.py`, `schemas/voice.py` |
| Line timing: transcript (`GeminiTranscriber`) → `match_dialogue`/`align_lines` windows; lines never heard get an estimated slot | `audio/voice/timing.py` |
| Time-fit: atempo clamped to [0.8, 1.25]; start at the lip onset, shift earlier into free space; never trims speech (only edge silence + inner pauses capped at 0.3 s); overrun is reported | `audio/voice/timefit.py`, `media.py` |
| Speech removal: `duck` (−18 dB ramped volume expression over all transcript segments) or `demucs` (htdemucs `no_vocals` + −6 dB residual duck) | `audio/voice/separation.py` |
| Mix: per-line loudnorm −16 LUFS → atempo → adelay, `amix normalize=0` over the bed, limiter; the video stream is copied | `audio/voice/mix.py` |
| Gemini TTS adapter (`gemini-2.5-flash-tts`, language-aware `language_code`, a single `Say …:` directive, a guard against instructions being read aloud, retry) | `adapters/gemini_tts.py` |
| Stage: runs after QA approval and before stitching; writes `GenerationRun.voiced_video_uri` + `voiceover` (append-only; `output_video_uri` stays the Omni original); S10 uses the voiced clip when `sync` | `pipeline/post_render/voiceover_stage.py`, `assembly/readiness.py` |

TTS models available on aug18-25-3: `gemini-2.5-flash-tts` and `gemini-2.5-pro-tts` (GA);
the `*-preview-tts` variants also respond. Output is 24 kHz PCM.

Voices assigned: **Pip → Zephyr (robot)**, **Ava → Despina (adult_female)**. Ava's gender
came from the story's pronouns ("in her left hand"); her attributes don't state it.

## Experiment

Clips (from `generation_runs.json` / `dialogue_lines.json`): `scn_001_01` (Ava),
`scn_003_02` (Pip), `scn_004_02` att2 (Pip), `scn_007_01` (Ava), `scn_007_02` att4
(Pip + Ava), `scn_008_01` att2 (Ava). There are 7 lines, and each clip was rendered with
both removers. Runner: `python -m storygraph.experiments.voiceover_sync`.

Files (scratch `61b7edc6…/scratch/`): originals `clips/orig/`, voiced `exp_v2/{duck,demucs}/`,
metrics `exp_v2/report.json`. The first run (`exp_v1/`) used the pre-fix prompt and timing.

### Results (v2, final code)

| Metric | Duck | Demucs |
|---|---|---|
| Lines heard complete (re-transcribe, similarity ≥ 0.8) | **7/7** (all 1.0) | **7/7** (all 1.0) |
| Onset offset vs Omni segment, median / max \|Δ\| | 0.0 / 0.40 s | 0.0 / 0.14 s |
| Bed level outside speech windows, Δ vs original | +0.4 dB on all 6 | ±0.5 dB on 5; **−7.3 dB on scn_003_02** |
| Residual Omni voice (Gemini listening) | 1/6 *clear* (scn_004_02 whisper) | 0/6 |
| Mix naturalness (Gemini, mean) | 0.74 | 0.80 |
| Voicing time per clip (8 vCPU; mostly Gemini calls) | 13–20 s | 10–17 s (TTS cached, includes separation) |

**Same voice across clips (Gemini audio judgement over per-clip excerpts):**

| Character | Omni original | Voiced |
|---|---|---|
| Pip | 0.45, **2 voices** ("young boy-like" ×2 + "deep calm adult male") | **1.0, 1 voice** ("calm, deadpan … slightly synthetic") |
| Ava | 1.0, 1 voice | 1.0, 1 voice |

Run v1 showed the same pattern: Pip 0.35 → 1.0. Median-F0 spread across clips: Pip
85 → 46 Hz. For Ava it rose from 15 to 61 Hz: the "storm has crossed this floor" line was
voiced at 271 Hz because the per-line `delivery` text steers pitch.

**Timing:** 6 of 7 lines hit the tempo cap (1.25×). The placed line ends exceed the end of
Omni's spoken window by a median of ≈ 1.7 s. `scn_007_02`: Pip overruns 1.48 s into Ava's
line, so the two lines overlap briefly; no words are cut.

### Listening notes (Gemini audio judge + metrics; no human listening yet)

- **scn_001_01, scn_007_01, scn_008_01, scn_003_02:** clean dialogue over the foley, room
  tone and clock ticks, with no bleed (0.82–0.88). On scn_003_02, demucs drops part of the
  bed (−7 dB).
- **scn_004_02 duck:** Omni's whisper "surrender your…" is still audible. It fell outside
  every transcript segment, so it was never ducked. Demucs removes it.
- **scn_007_02:** the bed is almost silent (−54 dB). Both lines sound "dry/studio" with
  either remover (0.45 / 0.60). Re-voicing can't add room tone that isn't there.
- **Pip's timbre:** Zephyr with the robot tone phrase sounds "calm, deadpan, low-pitched
  female, slightly synthetic". It is consistent, but the user may want a brighter or more
  robotic voice. Change it once with `set_voice(repo, "char_pip", …)`.

### Problems found and fixed during the experiment

1. Gemini TTS read the style instructions aloud: a 23 s clip for a 9-word line, including
   "Synthesize…". Fixed with a single `Say …:` directive, delivery text sanitised and capped
   at 6 words, and a length check that retries with the plain text only.
2. An overrunning line pushed the next line past the end of the clip. Now a line never
   starts later than its own onset.
3. Long dramatic pauses inside TTS lines forced the tempo to its cap. Inner pauses are now
   capped at 0.3 s without touching speech.
4. The shared project hit 429 TPM limits. Added experiment backoff. In the pipeline,
   per-shot failures fall back to the Omni clip and are logged.

## Separation vs ducking — recommendation

**Use ducking as the default. Demucs should be opt-in (`speech_removal: demucs`) only on
an image that ships it.**

- **Ducking:** no dependencies, sub-second ffmpeg, and the bed outside speech is untouched
  on 6/6 clips. Its weakness is Omni speech the transcriber misses (whispers), which stays
  audible (1/6). Cheap mitigation: also duck regions where `audio_voiced_ratio` detects
  voice.
- **Demucs (htdemucs, CPU):** cleanest result (0 residual, +0.06 naturalness), but it
  removed bed content on 1/6 clips. The runtime is heavy: torch 2.14 + demucs 4.1 installed
  as **5.4 GB** here (default CUDA wheels: torch 1.1 GB, nvidia 3.2 GB, triton 0.9 GB). A
  CPU-only torch is still roughly 1 GB plus ~80 MB of model weights, plus cold-start model
  load in Cloud Run. Separation itself takes a few CPU-seconds per 8 s clip.

**Before switching `audio.voiceover` to `sync`:**

1. Listen to `exp_v2/duck/*.mp4` against `clips/orig/*.mp4`.
2. Fix the end-of-line drift. Options: allow `tempo_max` up to 1.4, ask TTS for a brisker
   pace, or drop `delivery` steering (this also cuts Ava's pitch spread).
3. Confirm Pip's voice choice.
