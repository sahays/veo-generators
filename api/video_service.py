import os
import zlib
import asyncio
from typing import Optional
from google import genai
from google.genai import types
from models import Scene, Project


class VideoService:
    def __init__(self, storage_svc=None):
        self.project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
        self.veo_location = os.getenv("VEO_REGION", "us-central1")
        self.storage_svc = storage_svc

        self.video_client = genai.Client(
            vertexai=True, project=self.project_id, location=self.veo_location
        )

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

    async def generate_scene_video(
        self,
        project_id: str,
        scene: Scene,
        blocking: bool = True,
        project: Optional[Project] = None,
        prompt_override: Optional[str] = None,
    ):
        model_id = os.getenv("VIDEO_GEN_MODEL", "veo-3.1-generate-preview")
        seed = self._get_project_seed(project_id)

        SUPPORTED_DURATIONS = [4, 6, 8]
        try:
            start = self._parse_timestamp(scene.timestamp_start)
            end = self._parse_timestamp(scene.timestamp_end)
            raw = int(end - start)
            duration = min(SUPPORTED_DURATIONS, key=lambda d: abs(d - raw))
        except (ValueError, IndexError):
            duration = 8

        enriched_prompt = prompt_override or self._build_video_prompt(
            scene, project, duration
        )

        generate_kwargs = {
            "model": model_id,
            "prompt": enriched_prompt,
            "config": types.GenerateVideosConfig(
                durationSeconds=duration,
                seed=seed,
                aspectRatio=project.orientation if project else "16:9",
                numberOfVideos=1,
            ),
        }

        ref_url = None
        if scene.thumbnail_url and scene.thumbnail_url.startswith("gs://"):
            ref_url = scene.thumbnail_url
        elif project and project.reference_image_url:
            ref_url = project.reference_image_url
        if ref_url and ref_url.startswith("gs://"):
            generate_kwargs["image"] = types.Image(
                gcs_uri=ref_url, mime_type="image/png"
            )

        operation = self.video_client.models.generate_videos(**generate_kwargs)

        if not blocking:
            return {
                "operation_name": operation.name,
                "status": "processing",
                "generated_prompt": enriched_prompt,
            }

        while not operation.done:
            await asyncio.sleep(10)

        if operation.result and operation.result.generated_videos:
            return {
                "video_uri": operation.result.generated_videos[0].video.uri,
                "generated_prompt": enriched_prompt,
            }

        return {"video_uri": "", "generated_prompt": enriched_prompt}

    async def get_video_generation_status(self, operation_name: str):
        try:
            print(f"Checking operation: {operation_name}")

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
