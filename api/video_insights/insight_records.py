"""Record construction shared by the scene analysis and engagement routers.

Both features queue a `SceneAnalysisRecord` for a video: the scene analysis
router on request, the engagement router when the chosen video has no usable
analysis yet. They build it here so the two create paths cannot drift apart.
Pure module: no I/O.
"""

from __future__ import annotations

from typing import Any, Optional

from models import SceneAnalysisRecord
from source_resolver import ResolvedSource

PENDING = "pending"


def build_scene_analysis_record(
    source: ResolvedSource,
    *,
    display_name: str = "",
    focus: str = "",
    model_id: Optional[str] = None,
    region: Optional[str] = None,
    invite_code: Optional[str] = None,
) -> SceneAnalysisRecord:
    """A new `pending` scene analysis of a source the server resolved itself.

    The video location, filename and MIME type always come from `source`,
    never from the request. `invite_code` is stored as provenance only.
    """
    return SceneAnalysisRecord(
        source_type=source.source_type,
        source_id=source.source_id,
        video_gcs_uri=source.gcs_uri,
        video_filename=source.filename,
        display_name=display_name.strip(),
        mime_type=source.mime_type,
        focus=focus.strip(),
        model_id=model_id,
        region=region,
        status=PENDING,
        invite_code=invite_code,
    )


def requeue_updates(_record: Any) -> dict[str, Any]:
    """Fields that put a failed insight job back in the queue.

    The worker resumes from the job's GCS checkpoints, so finished work is
    not repeated.
    """
    return {
        "status": PENDING,
        "error_message": None,
        "progress_pct": 0,
        "stage": "",
        "stage_detail": "",
    }
