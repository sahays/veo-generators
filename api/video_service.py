import os
import zlib
import base64
import asyncio
from typing import Optional
from google import genai
from google.genai import types
from ai_helpers import resolve_model
from models import Scene, Project
from prompt_templates import PHYSICAL_REALISM_DIRECTIVE, VEO_NEGATIVE_PROMPT


def _is_omni_model(model_id: str) -> bool:
    return model_id.startswith("gemini-omni")


class VideoService:
    def __init__(self, storage_svc=None, firestore_svc=None):
        self.project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
        self.veo_location = os.getenv("VEO_REGION", "global")
        self.storage_svc = storage_svc
        self.firestore_svc = firestore_svc

        self.video_client = genai.Client(
            vertexai=True, project=self.project_id, location=self.veo_location
        )
        self._clients: dict[str, genai.Client] = {self.veo_location: self.video_client}

    def _get_client(self, region: str | None = None) -> genai.Client:
        loc = region or self.veo_location
        if loc not in self._clients:
            self._clients[loc] = genai.Client(
                vertexai=True, project=self.project_id, location=loc
            )
        return self._clients[loc]

    def _get_project_seed(self, project_id: str) -> int:
        return zlib.adler32(project_id.encode()) & 0x7FFFFFFF

    def _parse_timestamp(self, ts: str) -> float:
        """Parse '00:05' or '5' to seconds."""
        if ":" in ts:
            parts = ts.split(":")
            return int(parts[0]) * 60 + float(parts[1])
        return float(ts)

    def _build_video_prompt(
        self, scene: Scene, project: Optional[Project], duration: int
    ) -> str:
        """Build a video-specific prompt with duration and camera movement."""
        parts = []
        parts.append(f"{duration}-second video clip.")
        orientation = project.orientation if project else None
        if orientation == "9:16":
            parts.append("Aspect ratio: 9:16 (portrait/vertical).")
        elif orientation == "16:9":
            parts.append("Aspect ratio: 16:9 (landscape/horizontal).")
        elif orientation:
            parts.append(f"Aspect ratio: {orientation}.")
        if scene.metadata:
            md = scene.metadata
            if md.camera_angle:
                parts.append(f"Camera angle: {md.camera_angle}.")
            if md.camera_movement:
                parts.append(f"Camera movement: {md.camera_movement}.")
            if md.cinematic_style:
                parts.append(f"Cinematic style: {md.cinematic_style}.")
            pace = md.pace or (
                project.global_style.pace if project and project.global_style else None
            )
            if pace:
                parts.append(f"Pace: {pace}.")
        elif project and project.global_style and project.global_style.pace:
            parts.append(f"Pace: {project.global_style.pace}.")
        if project and project.global_style:
            gs = project.global_style
            parts.append(
                f"Style: {gs.look}. Mood: {gs.mood}. "
                f"Colors: {gs.color_grading}. Lighting: {gs.lighting_style}."
            )
        if project and project.continuity and project.continuity.characters:
            char_descs = []
            for c in project.continuity.characters:
                char_descs.append(f"{c.id}: {c.description}, wearing {c.wardrobe}")
            parts.append(f"Characters: {'; '.join(char_descs)}.")
        if project and project.continuity and project.continuity.setting_notes:
            parts.append(f"Setting: {project.continuity.setting_notes}.")
        parts.append(scene.visual_description)
        parts.append(PHYSICAL_REALISM_DIRECTIVE)

        # Visual enter/exit transitions are intentionally NOT sent to Veo: it
        # generates each clip in isolation, so "connecting" language makes it
        # morph objects in-frame. Transitions are applied at stitch time.
        if scene.music_transition:
            parts.append(f"Music transition: {scene.music_transition}")

        if scene.narration_enabled and scene.narration:
            parts.append(f'Voice-over narration: "{scene.narration}"')

        if scene.music_enabled:
            music = scene.music_description
            if (
                not music
                and project
                and project.global_style
                and project.global_style.soundtrack_style
            ):
                music = project.global_style.soundtrack_style
            if music:
                parts.append(f"Background music: {music}.")

        return " ".join(parts)

    def _extract_omni_video_uri(self, interaction, name_hint: str) -> Optional[str]:
        """Extract a gs:// URI from a completed Gemini Omni interaction,
        uploading inline base64 bytes if needed."""
        output_video = getattr(interaction, "output_video", None)
        if output_video is None and isinstance(interaction, dict):
            output_video = interaction.get("output_video")

        if output_video is None:
            steps = getattr(interaction, "steps", None)
            if steps is None and isinstance(interaction, dict):
                steps = interaction.get("steps")
            for step in reversed(steps or []):
                step_type = (
                    step.get("type")
                    if isinstance(step, dict)
                    else getattr(step, "type", None)
                )
                if step_type != "model_output":
                    continue
                content = (
                    step.get("content")
                    if isinstance(step, dict)
                    else getattr(step, "content", None)
                )
                for item in reversed(content or []):
                    item_type = (
                        item.get("type")
                        if isinstance(item, dict)
                        else getattr(item, "type", None)
                    )
                    if item_type == "video":
                        output_video = item
                        break
                if output_video is not None:
                    break

        if output_video is None:
            return None

        uri = (
            output_video.get("uri")
            if isinstance(output_video, dict)
            else getattr(output_video, "uri", None)
        )
        if uri:
            return uri

        data = (
            output_video.get("data")
            if isinstance(output_video, dict)
            else getattr(output_video, "data", None)
        )
        if data and self.storage_svc:
            video_bytes = (
                base64.b64decode(data) if isinstance(data, str) else bytes(data)
            )
            safe_name = name_hint.replace("/", "_").replace(":", "_")
            filename = f"videos/{safe_name}.mp4"
            return self.storage_svc.upload_bytes(
                video_bytes, filename, content_type="video/mp4"
            )
        return None

    async def generate_scene_video(
        self,
        project_id: str,
        scene: Scene,
        blocking: bool = True,
        project: Optional[Project] = None,
        prompt_override: Optional[str] = None,
        model_id: Optional[str] = None,
        region: Optional[str] = None,
    ):
        model_id = resolve_model(
            self.firestore_svc,
            "video",
            "VIDEO_GEN_MODEL",
            "gemini-omni-1.1-flash-preview",
            model_id,
        )
        is_omni = _is_omni_model(model_id)
        # Gemini Omni 1.1 Flash is only available on the global endpoint.
        client = self._get_client("global" if is_omni else region)
        seed = self._get_project_seed(project_id)

        supported_durations = list(range(3, 11)) if is_omni else [4, 6, 8]
        try:
            start = self._parse_timestamp(scene.timestamp_start)
            end = self._parse_timestamp(scene.timestamp_end)
            raw = int(end - start)
            duration = min(supported_durations, key=lambda d: abs(d - raw))
        except (ValueError, IndexError):
            duration = 8

        enriched_prompt = prompt_override or self._build_video_prompt(
            scene, project, duration
        )

        ref_url = None
        if scene.thumbnail_url and scene.thumbnail_url.startswith("gs://"):
            ref_url = scene.thumbnail_url
        elif project and project.reference_image_url:
            ref_url = project.reference_image_url

        if is_omni:
            input_blocks: list[dict] = [{"type": "text", "text": enriched_prompt}]
            video_task = "text_to_video"
            if ref_url and ref_url.startswith("gs://"):
                input_blocks.append(
                    {"type": "image", "uri": ref_url, "mime_type": "image/png"}
                )
                video_task = "image_to_video"

            response_format_block: dict = {
                "type": "video",
                "aspect_ratio": project.orientation
                if project and project.orientation
                else "16:9",
                "resolution": "720p",
                "duration": f"{duration}s",
            }
            bucket = os.getenv("GCS_BUCKET")
            if bucket:
                response_format_block["delivery"] = "uri"
                response_format_block["gcs_uri"] = f"gs://{bucket}/videos/{project_id}/"

            interaction = client.interactions.create(
                model=model_id,
                background=not blocking,
                input=input_blocks,
                response_format=[response_format_block],
                generation_config={"video_config": {"task": video_task}},
            )
            interaction_id = getattr(interaction, "id", None) or (
                interaction.get("id") if isinstance(interaction, dict) else ""
            )

            if not blocking:
                return {
                    "operation_name": f"interaction:{interaction_id}",
                    "status": "processing",
                    "generated_prompt": enriched_prompt,
                    "model_id": model_id,
                    "duration_seconds": duration,
                }

            while getattr(interaction, "status", None) in ("in_progress", "queued"):
                await asyncio.sleep(10)
                interaction = client.interactions.get(interaction_id)

            uri = self._extract_omni_video_uri(
                interaction, interaction_id or project_id
            )
            return {
                "video_uri": uri or "",
                "generated_prompt": enriched_prompt,
                "model_id": model_id,
                "duration_seconds": duration,
            }

        generate_kwargs = {
            "model": model_id,
            "prompt": enriched_prompt,
            "config": types.GenerateVideosConfig(
                duration_seconds=duration,
                seed=seed,
                aspect_ratio=project.orientation if project else "16:9",
                number_of_videos=1,
                generate_audio=True,
                person_generation="allow_all",
                resolution="720p",
                negative_prompt=VEO_NEGATIVE_PROMPT,
            ),
        }
        if ref_url and ref_url.startswith("gs://"):
            generate_kwargs["image"] = types.Image(
                gcs_uri=ref_url, mime_type="image/png"
            )

        operation = client.models.generate_videos(**generate_kwargs)

        if not blocking:
            return {
                "operation_name": operation.name,
                "status": "processing",
                "generated_prompt": enriched_prompt,
                "model_id": model_id,
                "duration_seconds": duration,
            }

        while not operation.done:
            await asyncio.sleep(10)

        if operation.result and operation.result.generated_videos:
            return {
                "video_uri": operation.result.generated_videos[0].video.uri,
                "generated_prompt": enriched_prompt,
                "model_id": model_id,
                "duration_seconds": duration,
            }

        return {
            "video_uri": "",
            "generated_prompt": enriched_prompt,
            "model_id": model_id,
            "duration_seconds": duration,
        }

    async def get_video_generation_status(self, operation_name: str):
        try:
            print(f"Checking operation: {operation_name}")

            if operation_name.startswith("interaction:"):
                interaction_id = operation_name.split("interaction:", 1)[1]
                client = self._get_client("global")
                interaction = client.interactions.get(interaction_id)
                status = getattr(interaction, "status", None) or (
                    interaction.get("status") if isinstance(interaction, dict) else None
                )
                if status in ("in_progress", "queued", None):
                    return {"status": "processing"}
                if status in (
                    "failed",
                    "cancelled",
                    "incomplete",
                    "budget_exceeded",
                ):
                    errors = getattr(interaction, "errors", None) or (
                        interaction.get("errors")
                        if isinstance(interaction, dict)
                        else None
                    )
                    return {"status": "failed", "error": str(errors or status)}
                if status == "completed":
                    uri = self._extract_omni_video_uri(interaction, interaction_id)
                    if uri:
                        print(f"Video generated (Gemini Omni): {uri}")
                        return {"status": "completed", "video_uri": uri}
                    print("Interaction complete but no video found in result.")
                    return {"status": "completed", "video_uri": None}
                return {"status": "processing"}

            operation_wrapper = types.GenerateVideosOperation(name=operation_name)
            operation = self.video_client.operations.get(operation_wrapper)
            print(f"Operation type: {type(operation)}")

            is_done = getattr(operation, "done", None)
            if is_done is None and isinstance(operation, dict):
                is_done = operation.get("done")

            if is_done:
                error = getattr(operation, "error", None)
                if error is None and isinstance(operation, dict):
                    error = operation.get("error")

                if error:
                    print(f"Operation failed: {error}")
                    return {"status": "failed", "error": str(error)}

                result = getattr(operation, "result", None)
                if result is None and isinstance(operation, dict):
                    result = operation.get("result")

                if result:
                    videos = getattr(result, "generated_videos", None)
                    if videos is None and isinstance(result, dict):
                        videos = result.get("generated_videos")

                    if videos:
                        first_video = videos[0]

                        uri = (
                            getattr(first_video.video, "uri", None)
                            if hasattr(first_video, "video")
                            else None
                        )

                        if not uri:
                            video_bytes = (
                                getattr(first_video.video, "video_bytes", None)
                                if hasattr(first_video, "video")
                                else None
                            )
                            if video_bytes and self.storage_svc:
                                safe_name = operation_name.replace("/", "_")
                                filename = f"videos/{safe_name}.mp4"
                                print(f"Uploading raw video bytes to {filename}...")
                                uri = self.storage_svc.upload_bytes(
                                    video_bytes, filename, content_type="video/mp4"
                                )

                        if uri is None and isinstance(first_video, dict):
                            video_obj = first_video.get("video")
                            uri = (
                                video_obj.get("uri")
                                if isinstance(video_obj, dict)
                                else getattr(video_obj, "uri", None)
                            )

                        if uri:
                            print(f"Video generated: {uri}")
                            return {"status": "completed", "video_uri": uri}

                print("Operation complete but no video found in result.")
                return {"status": "completed", "video_uri": None}

            return {"status": "processing"}
        except Exception as e:
            print(f"Error checking status: {e}")
            import traceback

            traceback.print_exc()
            return {"status": "error", "message": str(e)}
