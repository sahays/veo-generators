"""Brief analysis, storyboard review, and video evaluation parsing helpers."""

from datetime import datetime
from models import (
    Continuity,
    Scene,
    SceneEvalFinding,
    SceneMetadata,
    StoryboardReviewIssue,
    StoryboardReviewReport,
    VideoEvalReport,
)


def parse_scenes(data) -> tuple:
    """Parse Gemini response into Scene objects, global_style, continuity."""
    global_style = continuity = None
    if isinstance(data, dict):
        global_style = data.get("global_style")
        continuity = data.get("continuity")
        data = data.get("scenes", data)
    if not isinstance(data, list):
        return [], None, None

    scenes = []
    for s in data:
        metadata = s.get("metadata", {})
        if "character" in metadata and isinstance(metadata["character"], str):
            metadata["characters"] = [metadata.pop("character")]
        scenes.append(
            Scene(
                visual_description=s["visual_description"],
                timestamp_start=s["timestamp_start"],
                timestamp_end=s["timestamp_end"],
                metadata=SceneMetadata(**metadata),
                narration=s.get("narration"),
                narration_enabled=bool(s.get("narration")),
                speaker_notes=s.get("speaker_notes"),
                music_description=s.get("music_description"),
                music_enabled=bool(s.get("music_description")),
                enter_transition=s.get("enter_transition"),
                exit_transition=s.get("exit_transition"),
                music_transition=s.get("music_transition"),
            )
        )
    return scenes, global_style, continuity


def merge_reviewed_scenes(
    existing_scenes: list[Scene], reviewed_raw: list[dict]
) -> list[Scene]:
    """Merge reviewed scene updates into existing Scene objects while preserving IDs and media URLs."""
    if not reviewed_raw:
        return existing_scenes
    merged: list[Scene] = []
    for idx, rev in enumerate(reviewed_raw):
        base = existing_scenes[idx] if idx < len(existing_scenes) else None
        md_raw = rev.get("metadata") or (
            base.metadata.dict() if base and base.metadata else {}
        )
        if "character" in md_raw and isinstance(md_raw["character"], str):
            md_raw["characters"] = [md_raw.pop("character")]
        narration = (
            rev.get("narration")
            if "narration" in rev
            else (base.narration if base else None)
        )
        music_desc = (
            rev.get("music_description")
            if "music_description" in rev
            else (base.music_description if base else None)
        )
        if base:
            updated = base.copy(
                update={
                    "visual_description": rev.get("visual_description")
                    or base.visual_description,
                    "timestamp_start": rev.get("timestamp_start")
                    or base.timestamp_start,
                    "timestamp_end": rev.get("timestamp_end") or base.timestamp_end,
                    "narration": narration,
                    "narration_enabled": bool(narration)
                    if narration is not None
                    else base.narration_enabled,
                    "speaker_notes": rev.get("speaker_notes") or base.speaker_notes,
                    "music_description": music_desc,
                    "music_enabled": bool(music_desc)
                    if music_desc is not None
                    else base.music_enabled,
                    "enter_transition": rev.get(
                        "enter_transition", base.enter_transition
                    ),
                    "exit_transition": rev.get("exit_transition", base.exit_transition),
                    "music_transition": rev.get(
                        "music_transition", base.music_transition
                    ),
                    "metadata": SceneMetadata(**md_raw),
                }
            )
            merged.append(updated)
        else:
            merged.append(
                Scene(
                    visual_description=rev.get("visual_description", ""),
                    timestamp_start=rev.get("timestamp_start", "00:00"),
                    timestamp_end=rev.get("timestamp_end", "00:08"),
                    narration=narration,
                    narration_enabled=bool(narration),
                    speaker_notes=rev.get("speaker_notes"),
                    music_description=music_desc,
                    music_enabled=bool(music_desc),
                    enter_transition=rev.get("enter_transition"),
                    exit_transition=rev.get("exit_transition"),
                    music_transition=rev.get("music_transition"),
                    metadata=SceneMetadata(**md_raw),
                )
            )
    if len(existing_scenes) > len(merged):
        merged.extend(existing_scenes[len(merged) :])
    return merged


def parse_review_response(
    parsed: dict | None, existing_scenes: list[Scene], usage=None
) -> dict:
    """Parse Gemini storyboard review output into report, continuity, and merged scenes."""
    payload = parsed if isinstance(parsed, dict) else {}
    issues = [
        StoryboardReviewIssue(
            scene_number=int(it.get("scene_number", 0)),
            category=it.get("category", "continuity"),
            severity=it.get("severity", "warning"),
            problem=it.get("problem", ""),
            fix_applied=it.get("fix_applied", ""),
        )
        for it in (payload.get("issues") or [])
        if isinstance(it, dict)
    ]
    report_kwargs: dict = {
        "overall_score": int(payload.get("overall_score", 95)),
        "summary": payload.get(
            "summary", "Storyboard reviewed and continuity constraints applied."
        ),
        "issues": issues,
        "reviewed_at": datetime.utcnow(),
    }
    if usage is not None:
        report_kwargs["usage"] = usage
    report = StoryboardReviewReport(**report_kwargs)
    cont_raw = payload.get("continuity")
    continuity = Continuity(**cont_raw) if isinstance(cont_raw, dict) else None
    scenes = merge_reviewed_scenes(existing_scenes, payload.get("scenes") or [])
    return {
        "review_report": report,
        "continuity": continuity,
        "scenes": scenes,
    }


def parse_eval_response(
    parsed: dict | None, scenes: list[Scene], iteration: int = 1, usage=None
) -> VideoEvalReport:
    """Parse Gemini finished-video evaluation output into a VideoEvalReport."""
    payload = parsed if isinstance(parsed, dict) else {}
    findings: list[SceneEvalFinding] = []
    for item in payload.get("findings") or []:
        if not isinstance(item, dict):
            continue
        scene_num = max(1, int(item.get("scene_number", 1)))
        scene_id = scenes[scene_num - 1].id if scene_num <= len(scenes) else None
        findings.append(
            SceneEvalFinding(
                scene_number=scene_num,
                scene_id=scene_id,
                category=item.get("category", "continuity"),
                severity=item.get("severity", "critical"),
                observed_issue=item.get("observed_issue", ""),
                regenerate_frame=bool(item.get("regenerate_frame", False)),
                regenerate_video=bool(item.get("regenerate_video", True)),
                corrected_visual_description=item.get("corrected_visual_description"),
                corrected_speaker_notes=item.get("corrected_speaker_notes"),
                corrected_narration=item.get("corrected_narration"),
                corrected_music_description=item.get("corrected_music_description"),
            )
        )
    passed = bool(payload.get("passed", len(findings) == 0))
    eval_kwargs: dict = {
        "overall_score": int(payload.get("overall_score", 100 if passed else 65)),
        "passed": passed,
        "iteration": iteration,
        "summary": payload.get(
            "summary", "Finished video evaluated for continuity and realism."
        ),
        "findings": findings,
        "evaluated_at": datetime.utcnow(),
    }
    if usage is not None:
        eval_kwargs["usage"] = usage
    return VideoEvalReport(**eval_kwargs)
