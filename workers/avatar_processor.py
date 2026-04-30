"""Avatar turn processor — renders the lip-synced video for a pending AvatarTurn."""

import asyncio
import logging
import os
import zlib
from typing import Optional

from google.genai import types

import deps
from ai_helpers import resolve_model
from avatar_service import build_render_prompt
from base_processor import JobProcessor

logger = logging.getLogger(__name__)


VEO_AVATAR_MODEL_ENV = "AVATAR_VIDEO_MODEL"
VEO_AVATAR_MODEL_DEFAULT = "veo-3.1-fast-generate-001"


class AvatarProcessor(JobProcessor):
    """Renders a Veo Fast image-to-video for each pending AvatarTurn."""

    @property
    def name(self) -> str:
        return "avatar"

    @property
    def firestore_update_method(self) -> str:
        return "update_avatar_turn"

    def get_pending_records(self) -> list:
        return deps.firestore_svc.get_pending_avatar_turns()

    def process(self, turn) -> None:
        turn_id = turn.id
        avatar = deps.firestore_svc.get_avatar(turn.avatar_id)
        if not avatar:
            self.mark_failed(turn_id, f"Avatar {turn.avatar_id} not found")
            return

        # v2 avatars use Gemini Live and never produce render jobs. Defensive
        # check: if a turn somehow lands here for one (e.g. hand-edited doc),
        # fail it instead of trying to run Veo.
        if getattr(avatar, "version", "v1") != "v1":
            self.mark_failed(
                turn_id,
                "v2 avatars use the live session and do not render turns",
            )
            return

        self.update_status(turn_id, "generating", 10)
        logger.info(f"[avatar:{turn_id}] Rendering Veo Fast video")

        try:
            video_uri, used_model = self._render(turn, avatar)
        except Exception as e:
            logger.error(f"[avatar:{turn_id}] Veo render failed: {e}")
            self.mark_failed(turn_id, str(e))
            return

        if not video_uri:
            logger.error(f"[avatar:{turn_id}] Marking failed: Veo returned no video")
            self.mark_failed(turn_id, "Veo returned no video")
            return

        self.update_status(
            turn_id,
            "completed",
            100,
            video_gcs_uri=video_uri,
            model_id=used_model,
        )
        logger.info(f"[avatar:{turn_id}] Completed: {video_uri}")

    # ------------------------------------------------------------------
    # Veo invocation
    # ------------------------------------------------------------------

    def _render(self, turn, avatar) -> tuple[Optional[str], str]:
        if not deps.video_svc:
            raise RuntimeError("Video service unavailable")

        model_id = resolve_model(
            deps.firestore_svc,
            "video",
            VEO_AVATAR_MODEL_ENV,
            VEO_AVATAR_MODEL_DEFAULT,
            None,
        )
        client = deps.video_svc._get_client(turn.region)
        prompt = build_render_prompt(avatar, turn.answer_text)

        # Deterministic seed derived from the avatar id so every turn for the
        # same avatar uses the same seed — keeps the rendered character's look
        # (lighting, pose, framing) consistent across replies. Mirrors
        # `_get_project_seed` in api/video_service.py.
        seed = zlib.adler32(avatar.id.encode()) & 0x7FFFFFFF

        kwargs = {
            "model": model_id,
            "prompt": prompt,
            "config": types.GenerateVideosConfig(
                duration_seconds=8,
                seed=seed,
                aspect_ratio="9:16",
                number_of_videos=1,
                generate_audio=True,
                person_generation="allow_all",
                resolution="720p",
            ),
        }
        if avatar.image_gcs_uri.startswith("gs://"):
            kwargs["image"] = types.Image(
                gcs_uri=avatar.image_gcs_uri, mime_type="image/png"
            )

        operation = client.models.generate_videos(**kwargs)
        op_name = getattr(operation, "name", "<unknown>")
        logger.info(f"[avatar:{turn.id}] Veo op started: {op_name}")
        result = asyncio.run(self._await_operation(client, operation))
        video_uri = self._extract_video_uri(turn.id, result)
        return video_uri, model_id

    def _extract_video_uri(self, turn_id: str, result) -> Optional[str]:
        """Pull a usable gs:// URI out of the Veo result, uploading inline
        bytes when the SDK returned them instead of a URI. Raises with the
        Vertex AI safety reason when the output was filtered so the turn's
        error_message tells the user why instead of a generic 'no video'."""
        if not result:
            logger.warning(f"[avatar:{turn_id}] Veo result is None")
            return None
        videos = getattr(result, "generated_videos", None)
        if not videos:
            # RAI output filter — Veo generated the clip then blocked it.
            rai_reasons = getattr(result, "rai_media_filtered_reasons", None) or []
            rai_count = getattr(result, "rai_media_filtered_count", 0) or 0
            if rai_reasons or rai_count:
                msg = (
                    rai_reasons[0]
                    if rai_reasons
                    else f"{rai_count} videos blocked by Vertex AI safety filter"
                )
                logger.warning(f"[avatar:{turn_id}] RAI filter blocked output: {msg}")
                raise RuntimeError(f"Safety filter blocked the reply: {msg}")
            logger.warning(f"[avatar:{turn_id}] Veo result has no generated_videos")
            return None
        first = videos[0]
        video = getattr(first, "video", None)
        if not video:
            logger.warning(f"[avatar:{turn_id}] generated_videos[0] has no .video")
            return None
        uri = getattr(video, "uri", None)
        if uri:
            return uri
        video_bytes = getattr(video, "video_bytes", None)
        if video_bytes and deps.storage_svc:
            bucket = os.getenv("GCS_BUCKET")
            dest = f"avatars/turns/{turn_id}.mp4"
            logger.info(
                f"[avatar:{turn_id}] Veo returned bytes, uploading to gs://{bucket}/{dest}"
            )
            return deps.storage_svc.upload_bytes(
                video_bytes, dest, content_type="video/mp4"
            )
        logger.warning(f"[avatar:{turn_id}] Veo result has neither uri nor video_bytes")
        return None

    async def _await_operation(self, client, operation):
        """Poll the long-running op explicitly — the SDK doesn't auto-refresh
        `operation.done` for video generation. Raises with the Vertex error
        message when the op finishes with `error` set so we don't silently
        log 'result is None'."""
        max_wait_s = 600  # 10 min hard cap
        elapsed = 0
        while not operation.done and elapsed < max_wait_s:
            await asyncio.sleep(10)
            elapsed += 10
            try:
                operation = client.operations.get(operation)
            except Exception as e:
                logger.warning(f"operations.get failed mid-poll: {e}")
        if not operation.done:
            raise RuntimeError(f"Veo render did not complete within {max_wait_s}s")
        err = getattr(operation, "error", None)
        if err:
            raise RuntimeError(f"Veo operation failed: {err}")
        return operation.result
