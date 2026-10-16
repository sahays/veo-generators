"""Avatar turn processor — renders the lip-synced video for a pending AvatarTurn."""

import asyncio
import base64
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
VEO_AVATAR_MODEL_DEFAULT = "gemini-omni-1.1-flash-preview"


class AvatarProcessor(JobProcessor):
    """Renders an image-to-video clip for each pending AvatarTurn."""

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
        logger.info(f"[avatar:{turn_id}] Rendering avatar video")

        try:
            video_uri, used_model = self._render(turn, avatar)
        except Exception as e:
            logger.error(f"[avatar:{turn_id}] Video render failed: {e}")
            self.mark_failed(turn_id, str(e))
            return

        if not video_uri:
            logger.error(f"[avatar:{turn_id}] Marking failed: returned no video")
            self.mark_failed(turn_id, "Video model returned no video")
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
    # Video invocation (Gemini Omni 1.1 Flash & Veo)
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
        is_omni = model_id.startswith("gemini-omni")
        client = deps.video_svc._get_client("global" if is_omni else turn.region)
        prompt = build_render_prompt(avatar, turn.answer_text)

        if is_omni:
            video_uri = self._render_omni(client, model_id, turn, avatar, prompt)
            return video_uri, model_id

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

    def _render_omni(
        self, client, model_id: str, turn, avatar, prompt: str
    ) -> Optional[str]:
        input_blocks: list[dict] = [{"type": "text", "text": prompt}]
        video_task = "text_to_video"
        if avatar.image_gcs_uri.startswith("gs://"):
            input_blocks.append(
                {
                    "type": "image",
                    "uri": avatar.image_gcs_uri,
                    "mime_type": "image/png",
                }
            )
            video_task = "image_to_video"

        response_format_block: dict = {
            "type": "video",
            "aspect_ratio": "9:16",
            "resolution": "720p",
            "duration": "8s",
        }
        bucket = os.getenv("GCS_BUCKET")
        if bucket:
            response_format_block["delivery"] = "uri"
            response_format_block["gcs_uri"] = f"gs://{bucket}/avatars/turns/"

        interaction = client.interactions.create(
            model=model_id,
            background=True,
            input=input_blocks,
            response_format=[response_format_block],
            generation_config={"video_config": {"task": video_task}},
        )
        interaction = asyncio.run(self._await_interaction(client, interaction))
        output_video = getattr(interaction, "output_video", None)
        if output_video is not None:
            uri = getattr(output_video, "uri", None) or (
                output_video.get("uri") if isinstance(output_video, dict) else None
            )
            if uri:
                return uri
            data = getattr(output_video, "data", None) or (
                output_video.get("data") if isinstance(output_video, dict) else None
            )
            if data and deps.storage_svc:
                raw_bytes = (
                    base64.b64decode(data) if isinstance(data, str) else bytes(data)
                )
                dest = f"avatars/turns/{turn.id}.mp4"
                return deps.storage_svc.upload_bytes(
                    raw_bytes, dest, content_type="video/mp4"
                )
        return None

    async def _await_interaction(self, client, interaction):
        max_wait_s = 600
        elapsed = 0
        interaction_id = getattr(interaction, "id", None)
        while (
            getattr(interaction, "status", None) in ("in_progress", "queued")
            and elapsed < max_wait_s
        ):
            await asyncio.sleep(10)
            elapsed += 10
            try:
                interaction = client.interactions.get(interaction_id)
            except Exception as e:
                logger.warning(f"interactions.get failed mid-poll: {e}")
        status = getattr(interaction, "status", None)
        if status in ("in_progress", "queued"):
            raise RuntimeError(
                f"Gemini Omni render did not complete within {max_wait_s}s"
            )
        if status in ("failed", "cancelled", "incomplete", "budget_exceeded"):
            errors = getattr(interaction, "errors", None)
            raise RuntimeError(f"Gemini Omni operation failed: {errors or status}")
        return interaction

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
