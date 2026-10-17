# StoryGraph Root-Cause Analysis: Aranya Kand (`p-whqv0ofw`)

**Date:** 2026-10-17  
**Production ID:** `p-whqv0ofw` (`veo_generators_productions`, GCP Project `aug18-25-3`)  
**Graph Snapshot:** 12 entities, 12 appearances, 27 assets, 3 scenes, 5 events, 45 state facts, 15 dialogue lines, 6 shots, 13 generation runs, 2 change requests

This document traces six observed video generation defects in the **Aranya Kand** production back to the exact Firestore Knowledge Graph (KG) nodes in `p-whqv0ofw` and the corresponding code bugs in `productions_service/storygraph/`.

---

## 1. Inconsistencies in Speech (Char 1 says Char 2's words / Missing lines)

### What Happened in the `p-whqv0ofw` Graph
* **Multi-speaker dialogue packed into single shots**: Every shot in `p-whqv0ofw` packs 2–3 different speakers into a single 6–8s video generation call and marks all of them `speaking: True` simultaneously:
  * `shot_scn_001_01` (8.0s): Packs `dlg_scn_001_01` (`char_sita` $\rightarrow$ `char_ram`) and `dlg_scn_001_02` (`char_lakshman` $\rightarrow$ `char_ram`), while `cast` marks `char_sita`, `char_ram`, and `char_lakshman` all `speaking: True`. Meanwhile, `dlg_scn_001_03` (`char_ram` $\rightarrow$ `char_lakshman`: *"लक्ष्मण, तुम यहीं रहकर सीता की रक्षा करो।"*) is **dropped completely** from `shot.dialogue_ids` even though Beat 3 (`5.34–8.0s`) explicitly describes Ram speaking it.
  * `shot_scn_001_02` (6.1s): Packs `dlg_scn_001_04` (`char_ravan` $\rightarrow$ `char_sita`) and `dlg_scn_001_05` (`char_sita` $\rightarrow$ `char_ravan`) into one shot with both marked `speaking: True`.
  * `shot_scn_002_01` (7.0s): Packs 3 different speakers (`dlg_scn_002_01` Ram, `dlg_scn_002_02` Jatayu, `dlg_scn_002_03` Lakshman) into one shot with all three marked `speaking: True`.
  * `shot_scn_002_02` (6.5s): Packs `dlg_scn_002_04` (`char_jatayu`) and `dlg_scn_002_05` (`char_ram`) into one shot.
  * `shot_scn_003_01` (6.5s): Packs `dlg_scn_003_01` (`char_shabari`) and `dlg_scn_003_02` (`char_ram`) into one shot.
  * `shot_scn_003_02` (8.0s): Packs `dlg_scn_003_03` (`char_shabari` $\rightarrow$ `char_ram`) and `dlg_scn_003_04` (`char_lakshman` $\rightarrow$ `char_ram`), while dropping `dlg_scn_003_05` (`char_ram` $\rightarrow$ `char_shabari`: *"प्रणाम माता, हम किष्किंधा की ओर प्रस्थान करते हैं।"*) even though Beat 3 (`5.34–8.0s`) describes Ram speaking and `char_ram` is marked `speaking: True`.

### Root Causes in `productions_service/storygraph/`
1. **Multi-speaker shot packing & 21-word truncation (`director.py`)**:
   * In `productions_service/storygraph/agents/role/director.py` (`_select_shot_dialogues_and_duration`, lines 172–193), the Director greedily packs `dialogue_ids` into a shot up to `max_words = 21` without splitting shots by speaker (`speaker_id`), and silently drops lines beyond 21 words (`dlg_scn_001_03`, `dlg_scn_003_05`) if no subsequent shot claims them.
   * Fallback and recovery logic (`_build_fallback_shot_one`, `_build_fallback_shot_two`, lines 43–51, 124–136, and line 181) forcibly assigns `dlg_ids[:1]` to Shot 1 and marks `lead_id` (`chars[0]`) as `speaking=True` regardless of who actually speaks the line.
2. **Silent speaker overwrite (`screenwriter.py`)**:
   * In `productions_service/storygraph/agents/role/screenwriter.py` (`_persist_screenwriter_output`, lines 68–87), if `dl.speaker_id` is not in `valid_char_ids`, it silently overwrites `speaker_id` to `lead_id`.
3. **No speaker-to-position or timestamp binding in the compiled prompt (`compile.py` & `prompt_template.j2`)**:
   * In `productions_service/storygraph/agents/role/director.py` (`_resolve_shot_cast`, lines 196–226), any character with a dialogue line in the shot is marked `speaking=True` (and non-speakers are never reset to `speaking=False`).
   * In `productions_service/storygraph/compile.py` (`_build_cast_ctx`, `_build_props_and_dialogue_ctx`, lines 65–126) and `productions_service/storygraph/config/prompt_template.j2` (lines 3–19), `CHARACTER [left, MS]: ...` lines never include the `speaking` flag, and the `DIALOGUE:` block lists lines at the bottom without screen positions (`[left]`/`[center]`/`[right]`), without beat timestamps (`0.0–2.7s`), and without mapping to which reference image represents which speaker.
4. **Critic explicitly disables speech/lip-sync QA (`critic.py`)**:
   * In `productions_service/storygraph/agents/critic.py` (`_call_vlm_critic`, lines 97–125; `_compute_qa_verdict`, lines 140–157), the Critic only sends 3 static JPEG frames (`0%`, `50%`, `95%`) without audio or video to Gemini VLM, explicitly instructs the VLM `"Set dialogue_wer = 0.0"`, and hardcodes `d_wer = 0.0` in non-mock runs.

---

## 2. Both Characters Look the Same (Ram & Lakshman look like duplicates)

### What Happened in the `p-whqv0ofw` Graph
* In `run_shot_scn_002_01_att1_c734cd` and `run_shot_scn_002_01_att2_c57659`, the VLM Critic explicitly flagged:
  > `"Ram lacks his designated blue skin tone and features, appearing as a duplicate of Lakshman."`
* Inspecting the `compiled_prompt` stored on **every single `GenerationRun`** in `p-whqv0ofw` shows why:
  * `CHARACTER [center, MS]: Ram — Adorable chibi Ram rendered in a soft felted 3D toy aesthetic with rounded proportions and an oversized head. His skin i..., wearing An ascetic prince's forest-dweller ensemble comprising a buttercup-yellow dhoti draped in soft folds with peach-cream hem linings, a mint-green sash tied gently at the waist, simple polished wooden armlets, and a sleek miniature curved bow slung gracefully over one shoulder with a matching pastel quiver of toy-proportioned arrows..`
  * `CHARACTER [right, MS]: Lakshman — Lakshman stands with vigilant, loyal chibi charm in 3D stylized form with delicate felt-like micro-textures. He features..., wearing A forest ascetic ensemble styled in dreamy pastel tones: a soft buttercup-yellow woven dhoti of gentle felted cotton, complemented by a diagonally draped mint-green sash with subtle stitched border details. Across his back hangs a miniature polished wooden quiver wrapped in cotton-candy blue cords containing felt-fletched pastel arrows, accompanied by a small, curved wooden bow with smooth rounded contours..`

### Root Causes in `productions_service/storygraph/`
1. **`compile.py` truncates `visual_description` at 120 chars—right before Ram's blue skin tone**:
   * In `productions_service/storygraph/compile.py` (`_render_within_budget`, lines 182–197), when the full prompt exceeds `max_prompt_chars = 3500` (`config.py`, line 97), attempt 3 sets `truncate_descriptions = 120` via `_clip_text` (lines 59–62) while leaving `wardrobe` completely untruncated.
   * In `app_char_ram_default_v1`, `"His skin is a gentle pastel cotton-candy blue..."` starts at character 121 and is **cut off at `"His skin i..."`** in every shot.
   * In `app_char_lakshman_default_v1`, `"He features a warm peach-cream complexion..."` starts at character 121 and is **cut off at `"He features..."`** in every shot.
2. **Parallel isolated entity design produced identical wardrobes (`design_studio.py`)**:
   * In `productions_service/storygraph/agents/design_studio.py` (`_design_appearances_and_sheets`, lines 270–288), each entity's `Appearance` is generated in an isolated parallel thread without cross-character context or visual contrast rules. Both `char_ram` and `char_lakshman` received near-identical `wardrobe` descriptions (`buttercup-yellow dhoti`, `mint-green sash`, `miniature curved bow`, `pastel quiver`).
3. **Unlabeled 8-figure composite turnaround sheets with zero image-to-character mapping (`shots_and_assets.py`, `budget.py`, `gemini_video.py`)**:
   * `productions_service/storygraph/tools/write_tools/shots_and_assets.py` (`create_character_sheet`, lines 84–102) generates a 4-angle turnaround (`hero, front, side, back` = 4 figures per character in one image).
   * `productions_service/storygraph/budget.py` (`build_composite_sheet`, lines 58–95) stitches two characters' 4-angle sheets side-by-side (`ast_comp_20b312db6d2a_v1` = Lakshman + Ram; `ast_comp_b1297c2dd781_v1` = Jatayu + Lakshman) **with no text labels** (producing 8 chibi figures in a single reference image).
   * `productions_service/storygraph/adapters/gemini_video.py` (`_build_omni_input_blocks`, lines 95–109) passes one text prompt followed by raw `{"type": "image", "uri": ...}` blocks with **no text captions or index mapping** telling the video model which image (or which half of a composite image) corresponds to which character name.
   * Furthermore, in `_retry_omni_interaction` (`gemini_video.py`, lines 112–147), if the primary Omni call throws an exception, it retries with `input_blocks[1:2]` (only the first reference image) or falls back to `text_to_video` with zero reference images.

---

## 3. Characters Disappearing, Overlapping, and Suddenly Flipping Sides

### What Happened in the `p-whqv0ofw` Graph
* **Last-frame continuity (`first_frame_uri`) was silently dropped from EVERY Gemini Omni call**:
  * Even when `Shot.continue_from_last_frame = True` and `GenerationRun.first_frame_asset_id` was recorded (`ast_lastframe_shot_scn_001_01_v4` on `run_shot_scn_001_02_att2`, `ast_lastframe_shot_scn_002_01_v3` on `run_shot_scn_002_02_att1`, `ast_lastframe_shot_scn_003_01_v1` on `run_shot_scn_003_02_att1`), **the previous shot's last frame was never actually sent to Gemini Omni**.
* **Cast disappearance & spatial jumps across shots**:
  * In `run_shot_scn_001_01_att4_a6edc0` (marked `approved`), the VLM Critic reported `artifact_flags: ['missing_character_lakshman', 'inconsistent_character_design_sita']`, yet the shot passed QA.
  * Between `shot_scn_001_01` and `shot_scn_001_02`, `char_ram`, `char_lakshman`, and `char_maricha` vanish from `cast` while `continue_from_last_frame=True` claims the camera continues seamlessly from Shot 1's last frame.
  * Between `shot_scn_002_01` and `shot_scn_002_02`, `char_lakshman` jumps from `position: 'right'` (`MS`) to `position: 'background'` (`MCU`) while his reference sheet is packed into a composite sheet (`ast_comp_b1297c2dd781_v1`) alongside `char_jatayu`.
  * In `run_shot_scn_003_02_att1_5b65b9`, VLM flagged `['hallucinated_character', 'character_inconsistency', 'cast_dropout']`, and on retry (`run_shot_scn_003_02_att2_813112`), `first_frame` was explicitly wiped to `None`.

### Root Causes in `productions_service/storygraph/`
1. **Off-by-one slice in `_build_omni_input_blocks` drops `first_frame_uri` 100% of the time when 3 refs exist (`budget.py` & `gemini_video.py`)**:
   * `productions_service/storygraph/budget.py` (`select_references`, lines 235–278) fills `reference_assets` up to `max_slots = 3` (`selected[:max_slots]`) **without** reserving one of the 3 image slots for `first_frame`.
   * Then `productions_service/storygraph/adapters/gemini_video.py` (`_build_omni_input_blocks`, lines 100–108) appends the 3 `package.reference_uris` first, appends `package.first_frame_uri` as the **4th item**, and slices `image_uris[:max_refs]` (`image_uris[:3]`)—**discarding `first_frame_uri` on every shot in Aranya Kand!**
2. **Retries intentionally discard `prev_shot_last_frame` (`render_stage.py`)**:
   * In `productions_service/storygraph/pipeline/render_stage.py` (`_execute_shot_render_loop`, lines 140–153), `drop_lf = (attempt == 2 and ...)` or `any(r.status == Status.FAILED ...)` sets `drop_last_frame=True`, wiping `prev_shot_last_frame=None` on retries (`run_shot_scn_003_02_att2_813112`).
3. **Forced `position="center"` collision & no 180-degree spatial blocking rule (`director.py` & `invariants.py`)**:
   * In `productions_service/storygraph/agents/role/director.py` (`_resolve_shot_cast`, lines 196–226), if a speaking character was omitted from the raw LLM `cast`, the Director injects them with hardcoded `position="center"` even when another character already occupies `position="center"`, causing characters to **overlap** in the center of the frame.
   * Neither `director.py` nor `productions_service/storygraph/invariants.py` (`check_invariants`, lines 148–163) validates that characters preserve consistent `left`/`center`/`right` screen positions across consecutive shots in a scene.
4. **Multi-pose turnaround sheets cause character multiplication/overlap (`shots_and_assets.py` & `budget.py`)**:
   * Passing 4-pose turnaround sheets (and 8-pose composite sheets) into `image_to_video` without instructing the model that they are multi-angle sheets of a single character causes the video model to render multiple copies or overlapping poses in the frame.

---

## 4. The Fruit Basket (`obj_berries`) Changed to Something Else

### What Happened in the `p-whqv0ofw` Graph
* In Scene 3 (`scn_003`), the graph contains **four conflicting descriptions** of the berry container and **never passes `ast_obj_berries_default_v1` to the video generator**:
  1. **Shabari's character sheet (`ast_char_shabari_default_v1`)**: Generated with prompt *"She holds a small **woven reed basket** containing soft pink and lavender forest berries."* (A reed basket is baked directly into Shabari's character reference image).
  2. **The prop entity (`ast_obj_berries_default_v1`)**: Designed in isolation as *"wild forest berries resting inside a softly curved, miniature **woven lotus-leaf bowl**."*
  3. **The `compiled_prompt` on `shot_scn_003_01`**:
     * `PROP: Sweet Berries` is truncated at 120 chars right in the middle of the word `"bowl"`: `"...resting inside a softly curved, miniature woven lotus-leaf b...."`
     * `ACTION` Beat 1 calls it a `"curved leaf platter"`.
     * `AUDIO` SFX calls it a `"wicker basket creak"`.
     * `CHARACTER [left, MCU]: Shabari` omits `holding Sweet Berries` entirely.
  4. **In `shot_scn_003_01`'s `GenerationRun` (`run_shot_scn_003_01_att1_36257c`)**:
     * `ref_assets = ['ast_comp_20b312db6d2a_v1', 'ast_char_shabari_default_v1', 'ast_loc_shabari_ashram_default_v1']` — **`ast_obj_berries_default_v1` was dropped!**
  5. **In `shot_scn_003_02`**: `props=[]` — `obj_berries` was dropped from the shot's `prop_ids` altogether.

### Root Causes in `productions_service/storygraph/`
1. **Off-by-one `shot.order` bug expires Event 1's `holding` state before Shot 1 even starts (`screenwriter.py` & `director.py`)**:
   * In `productions_service/storygraph/agents/role/screenwriter.py` (`_persist_screenwriter_output`, lines 46–65), Scene 3 (`order=30`) creates `evt_004` at `order=30` (`sf_0035: char_shabari holding='obj_berries'` with validity `[30, 31)`) and `evt_005` at `order=31` (which sets `holding=None` from `31` onward).
   * In `productions_service/storygraph/agents/role/director.py` (`run_director_for_scene`, lines 288–290), Shot 1 (`idx=1`) is assigned `shot_order = scene.order + idx = 30 + 1 = 31`!
   * When `productions_service/storygraph/views.py` (`shot_view`, lines 75–80) queries `repo.state_at("char_shabari", 31)`, interval `[30, 31)` is half-open (`30 <= 31 < 31` is `False`), so **`holding='obj_berries'` is already expired in Shot 1!** (The same bug occurs in Scene 1: `shot_scn_001_01` has `order=11`, so during the Golden Deer shot, Sita's state is already `mood='terrified'` and Ravan is already at `loc_panchavati_hermitage` from `evt_002`).
   * Because `holding` is `None` in `shot_view`:
     * `productions_service/storygraph/budget.py` (`_collect_sorted_candidates`, lines 140–152) gives `obj_berries` a low score of `40` (unheld prop) instead of `80` (held prop), so `ast_obj_berries_default_v1` loses out to the 3 character/location slots and is never passed as a reference image.
     * `productions_service/storygraph/compile.py` (`_build_cast_ctx`, lines 72–90) sees `holding=None`, so `CHARACTER: Shabari` never says `holding Sweet Berries`.
2. **`compile.py` wipes `dropped_to_verbal`**:
   * When `ast_obj_berries_default_v1` is dropped from the 3 image slots, `select_references` (`budget.py`, lines 230–231) puts its full description into `dropped_to_verbal`. Then `_render_within_budget` (`compile.py`, line 188) hits attempt 3 (`([], False, 120)`), which **discards `dropped_verbal` (`[]`)** and truncates `PROP: Sweet Berries` at 120 chars (`"lotus-leaf b..."`).
3. **Character sheets bake props into character appearances (`design_studio.py`)**:
   * `productions_service/storygraph/agents/design_studio.py` (lines 84–120) does not forbid including held props in a character's default turnaround sheet, nor does it share `obj_berries`'s visual description when designing `char_shabari`.

---

## 5. Why the Critic (`critic.py`) Approved Broken Clips

Even when the VLM Critic caught these defects (e.g., `missing_character_lakshman` on `run_shot_scn_001_01_att4_a6edc0`), `evaluate_clip_qa` (`productions_service/storygraph/agents/critic.py`, lines 186–246) still marked the runs `APPROVED` due to four defects:
1. **Empty `face_similarity: {}` passes QA vacuously**: In `_compute_qa_verdict` (`critic.py`, lines 126–165), the VLM returned `face_similarity: {}` on **all 13 runs** of `p-whqv0ofw`. Because `for cid, sim in face_sim.items():` iterates over an empty dict, **zero character face/identity checks were ever enforced**, and missing characters from `shot.cast` were never penalized.
2. **`continuity_prev_shot` and `artifact_flags` are ignored in `passed`**: `_compute_qa_verdict` (`critic.py`, lines 158–183) never checks `continuity_prev_shot` or `artifact_flags` (such as `missing_character_lakshman` or `cast_dropout`) when computing `reasons` / `passed = len(reasons) == 0`.
3. **Last frame is approved *before* QA runs**: `evaluate_clip_qa` (`critic.py`, lines 211–221) registers `ast_lastframe_*` with `status=Status.APPROVED` **before** calling `_call_vlm_critic`, so failed attempts pollute the graph with approved last-frame assets.
4. **Retries reuse the exact same prompt and references**: When the Critic returns `suggested_fix="recompile_prompt"`, `_apply_critic_fix` (`productions_service/storygraph/pipeline/render_stage.py`, lines 105–120) only marks the shot `stale` without altering the shot or prompt, so attempts 1–4 of `shot_scn_001_01` re-ran with the **exact same `compiled_prompt` and `ref_assets`**.

---

## 6. Summary Matrix: Symptoms $\rightarrow$ Root Causes

| Symptom in Aranya Kand (`p-whqv0ofw`) | Primary Root Cause in `productions_service/storygraph/` |
| :--- | :--- |
| **1. Char 1 says Char 2's words / missing speech** | `director.py` (lines 172–226) packs multi-speaker lines into one shot & drops lines $>21$ words; `prompt_template.j2` (lines 3–19) doesn't bind `DIALOGUE` to character positions/timecodes; `critic.py` (lines 118–157) hardcodes `dialogue_wer = 0.0`. |
| **2. Both characters look the same** | `compile.py` (lines 182–197) truncates `visual_description` at 120 chars (`"His skin i..."`), slicing off Ram's blue skin tone; `design_studio.py` (lines 270–288) generates near-identical wardrobes in parallel isolation; `budget.py` (lines 58–95) & `gemini_video.py` (lines 95–109) pass unlabeled composite turnaround sheets with no image-to-name mapping. |
| **3. Characters disappearing** | `gemini_video.py` (lines 100–108) slices `image_uris[:3]`, dropping `first_frame_uri` (the 4th item) on every shot; `render_stage.py` (lines 140–153) drops `prev_shot_last_frame` on retries; `critic.py` (lines 126–183) ignores `face_similarity: {}` and `missing_character_*` flags. |
| **4. Suddenly appearing on the other side** | `gemini_video.py` (lines 100–108) drops `first_frame_uri`; `director.py` (lines 196–226) and `invariants.py` (lines 148–163) do not enforce spatial position (`left`/`center`/`right`) continuity across shots in a scene. |
| **5. Characters overlapping** | `director.py` (lines 214–225) injects missing speakers with hardcoded `position="center"` even when `"center"` is occupied; 4-angle/8-angle turnaround sheets in `shots_and_assets.py` (lines 84–102) & `budget.py` (lines 58–95) confuse `image_to_video` into rendering multiple/overlapping poses. |
| **6. Fruit basket (`obj_berries`) changed** | `director.py` (line 290) sets `shot_order = scene.order + idx` (`31` instead of `30`), expiring `sf_0035` (`holding='obj_berries'` on `[30, 31)`) before Shot 1 starts—so `ast_obj_berries_default_v1` gets low priority and is dropped from `ref_assets`, while `compile.py` wipes `dropped_to_verbal` and Shabari's sheet (`ast_char_shabari_default_v1`) has a conflicting reed basket baked in. |
