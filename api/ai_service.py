import os
import zlib
import asyncio
import uuid
from typing import List, Optional
from google import genai
from google.genai import types
from models import Scene, SceneMetadata, UsageMetrics, AIResponseWrapper
from google.cloud.video import transcoder_v1


class AIService:
    def __init__(self, storage_svc=None, firestore_svc=None):
        self.project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
        self.location = os.getenv("GEMINI_REGION", "global")
        self.veo_location = os.getenv("VEO_REGION", "us-central1")

        self.storage_svc = storage_svc
        self.firestore_svc = firestore_svc

        # Primary client for Text and Image
        self.client = genai.Client(
            vertexai=True, project=self.project_id, location=self.location
        )

        # Dedicated client for Video (as Veo may have limited regional availability)
        self.video_client = genai.Client(
            vertexai=True, project=self.project_id, location=self.veo_location
        )

        self.transcoder_client = transcoder_v1.TranscoderServiceClient()
        self.storage_svc = storage_svc

    def _get_project_seed(self, project_id: str) -> int:
        # Generate a deterministic integer seed from the alphanumeric project ID
        return zlib.adler32(project_id.encode()) & 0x7FFFFFFF

    async def analyze_brief(
        self,
        project_id: str,
        concept: str,
        length: str,
        orientation: str,
        prompt_id: Optional[str] = None,
        schema_id: Optional[str] = None,
    ) -> AIResponseWrapper:
        model_id = os.getenv("OPTIMIZE_PROMPT_MODEL", "gemini-3-pro-preview")

        # 1. Resolve Prompt
        system_prompt_text = """
        Act as a professional film director and scriptwriter. 
        Break the following creative brief into a scene-by-scene cinematic script.
        Total length: {length} seconds.
        Orientation: {orientation}.
        Each scene must be between 4 and 8 seconds.
        
        Creative Brief: {concept}
        
        Return a JSON list of scenes following the requested structure.
        """

        if self.firestore_svc:
            fs = self.firestore_svc
            if prompt_id:
                res = fs.get_resource(prompt_id)
                if res:
                    system_prompt_text = res.content
            else:
                res = fs.get_active_resource("prompt", "project-analysis")
                if res:
                    system_prompt_text = res.content

        prompt = system_prompt_text.format(
            length=length, orientation=orientation, concept=concept
        )

        # 2. Resolve Schema
        response_schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "visual_description": {"type": "string"},
                    "timestamp_start": {"type": "string"},
                    "timestamp_end": {"type": "string"},
                    "metadata": {
                        "type": "object",
                        "properties": {
                            "location": {"type": "string"},
                            "character": {"type": "string"},
                            "camera_angle": {"type": "string"},
                            "lighting": {"type": "string"},
                            "style": {"type": "string"},
                            "mood": {"type": "string"},
                        },
                    },
                },
                "required": ["visual_description", "timestamp_start", "timestamp_end"],
            },
        }

        if self.firestore_svc:
            fs = self.firestore_svc
            import json

            if schema_id:
                res = fs.get_resource(schema_id)
                if res:
                    response_schema = json.loads(res.content)
            else:
                res = fs.get_active_resource("schema", "project-analysis")
                if res:
                    response_schema = json.loads(res.content)

        response = self.client.models.generate_content(
            model=model_id,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json", response_schema=response_schema
            ),
        )

        scenes_data = response.parsed
        if isinstance(scenes_data, dict) and "scenes" in scenes_data:
            scenes_data = scenes_data["scenes"]

        scenes = []
        for s in scenes_data:
            metadata = s.get("metadata", {})
            # Handle legacy 'character' field by migrating to 'characters' list
            if "character" in metadata and isinstance(metadata["character"], str):
                metadata["characters"] = [metadata.pop("character")]

            scenes.append(
                Scene(
                    visual_description=s["visual_description"],
                    timestamp_start=s["timestamp_start"],
                    timestamp_end=s["timestamp_end"],
                    metadata=SceneMetadata(**metadata),
                )
            )

        usage = UsageMetrics(
            input_tokens=response.usage_metadata.prompt_token_count,
            output_tokens=response.usage_metadata.candidates_token_count,
            model_name=model_id,
            cost_usd=(response.usage_metadata.prompt_token_count * 0.00000125)
            + (response.usage_metadata.candidates_token_count * 0.00000375),
        )

        return AIResponseWrapper(data=scenes, usage=usage)

    async def generate_frame(
        self, project_id: str, description: str, orientation: str
    ) -> AIResponseWrapper:
        model_id = os.getenv("STORYBOARD_MODEL", "gemini-3-pro-image-preview")

        # Gemini 3 Pro Image uses generate_content for image generation
        response = self.client.models.generate_content(
            model=model_id,
            contents=description,
            config={
                "candidate_count": 1,
            },
        )

        image_url = "https://picsum.photos/800/450"

        if response.candidates and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if hasattr(part, "inline_data") and part.inline_data:
                    # Upload the generated image bytes to GCS
                    if self.storage_svc:
                        dest = f"generated/{project_id}/{uuid.uuid4()}.png"
                        gcs_uri = self.storage_svc.upload_bytes(
                            part.inline_data.data, dest
                        )
                        image_url = self.storage_svc.get_signed_url(gcs_uri)
                    break

        usage = UsageMetrics(model_name=model_id, cost_usd=0.03)
        return AIResponseWrapper(data=image_url, usage=usage)

    async def generate_scene_video(
        self, project_id: str, scene: Scene, blocking: bool = True
    ):
        model_id = os.getenv("VIDEO_GEN_MODEL", "veo-3.1-generate-preview")
        seed = self._get_project_seed(project_id)

        operation = self.video_client.models.generate_videos(
            model=model_id,
            prompt=scene.visual_description,
            config={
                "duration_seconds": 8,
                "seed": seed,
                "aspect_ratio": "16:9",
                "number_of_videos": 1,
            },
        )

        if not blocking:
            return {"operation_name": operation.name, "status": "processing"}

        # This is a long running operation. We need to poll for completion.
        while not operation.done:
            await asyncio.sleep(10)
            # In some SDK versions, we might need to verify if the object auto-updates.
            # If operation.done is a property that calls the API, this works.

        if operation.result and operation.result.generated_videos:
            return operation.result.generated_videos[0].video.uri

        return ""

    async def get_video_generation_status(self, operation_name: str):
        try:
            print(f"Checking operation: {operation_name}")

            # Reconstruct the operation object from the name string
            # This is necessary because client.operations.get() requires an object, not a string.
            from google.genai import types

            operation_wrapper = types.GenerateVideosOperation(name=operation_name)

            # Fetch the updated operation status
            operation = self.video_client.operations.get(operation_wrapper)
            print(f"Operation type: {type(operation)}")

            # Defensive check for different possible return types (Object vs Dict)
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
                    # Handle both object and dict results
                    videos = getattr(result, "generated_videos", None)
                    if videos is None and isinstance(result, dict):
                        videos = result.get("generated_videos")

                    if videos:
                        # videos might be a list of objects or dicts
                        first_video = videos[0]

                        # Try to get URI first
                        uri = (
                            getattr(first_video.video, "uri", None)
                            if hasattr(first_video, "video")
                            else None
                        )

                        # If no URI, check for video bytes
                        if not uri:
                            video_bytes = (
                                getattr(first_video.video, "video_bytes", None)
                                if hasattr(first_video, "video")
                                else None
                            )
                            if video_bytes and self.storage_svc:
                                # Upload bytes to GCS
                                # Use operation name as part of filename to be unique
                                safe_name = operation_name.replace("/", "_")
                                filename = f"videos/{safe_name}.mp4"
                                print(f"Uploading raw video bytes to {filename}...")
                                uri = self.storage_svc.upload_bytes(
                                    video_bytes, filename, content_type="video/mp4"
                                )

                        # Fallback for dict access if needed
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

    async def stitch_production(self, project_id: str, scene_uris: List[str]) -> str:
        # Transcoder API usually requires a specific region
        transcoder_loc = os.getenv("GOOGLE_CLOUD_LOCATION", "asia-south1")
        parent = f"projects/{self.project_id}/locations/{transcoder_loc}"
        output_uri = (
            f"gs://{os.getenv('GCS_BUCKET')}/productions/{project_id}/final.mp4"
        )

        inputs = [
            transcoder_v1.types.Input(key=f"input{i}", uri=uri)
            for i, uri in enumerate(scene_uris)
        ]
        edit_list = [
            transcoder_v1.types.EditAtom(
                key=f"atom{i}", inputs=[f"input{i}"], start_time_offset="0s"
            )
            for i in range(len(scene_uris))
        ]

        job = transcoder_v1.types.Job()
        job.output_uri = output_uri
        job.config = transcoder_v1.types.JobConfig(
            inputs=inputs,
            edit_list=edit_list,
            elementary_streams=[
                transcoder_v1.types.ElementaryStream(
                    key="v1",
                    video_stream=transcoder_v1.types.VideoStream(
                        h264=transcoder_v1.types.VideoStream.H264CodecSettings(
                            bitrate_bps=5000000,
                            frame_rate=30,
                            height_pixels=720,
                            width_pixels=1280,
                        )
                    ),
                )
            ],
            mux_streams=[
                transcoder_v1.types.MuxStream(
                    key="final", container="mp4", elementary_streams=["v1"]
                )
            ],
        )

        self.transcoder_client.create_job(parent=parent, job=job)
        return output_uri
