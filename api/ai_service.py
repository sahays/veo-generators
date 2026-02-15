import os
import zlib
import asyncio
from typing import List
from google import genai
from google.genai import types
from models import Scene, SceneMetadata, UsageMetrics, AIResponseWrapper
from google.cloud.video import transcoder_v1

class AIService:
    def __init__(self):
        self.project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
        self.client = genai.Client(
            vertexai=True, 
            project=self.project_id, 
            location="us-central1"
        )
        self.transcoder_client = transcoder_v1.TranscoderServiceClient()

    def _get_project_seed(self, project_id: str) -> int:
        # Generate a deterministic integer seed from the alphanumeric project ID
        return zlib.adler32(project_id.encode()) & 0x7fffffff

    async def analyze_brief(self, project_id: str, concept: str, length: str, orientation: str) -> AIResponseWrapper:
        model_id = "gemini-3-pro-preview"
        
        # We define the schema for Gemini to return a structured list of scenes
        prompt = f"""
        Act as a professional film director and scriptwriter. 
        Break the following creative brief into a scene-by-scene cinematic script.
        Total length: {length} seconds.
        Orientation: {orientation}.
        Each scene must be between 4 and 8 seconds.
        
        Creative Brief: {concept}
        
        Return a JSON list of scenes following the requested structure.
        """

        response = self.client.models.generate_content(
            model=model_id,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema={
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
                                    "mood": {"type": "string"}
                                }
                            }
                        },
                        "required": ["visual_description", "timestamp_start", "timestamp_end"]
                    }
                }
            )
        )

        scenes_data = response.parsed
        scenes = [
            Scene(
                visual_description=s["visual_description"],
                timestamp_start=s["timestamp_start"],
                timestamp_end=s["timestamp_end"],
                metadata=SceneMetadata(**s.get("metadata", {}))
            ) for s in scenes_data
        ]

        usage = UsageMetrics(
            input_tokens=response.usage_metadata.prompt_token_count,
            output_tokens=response.usage_metadata.candidates_token_count,
            model_name=model_id,
            cost_usd=(response.usage_metadata.prompt_token_count * 0.00000125) + 
                     (response.usage_metadata.candidates_token_count * 0.00000375)
        )

        return AIResponseWrapper(data=scenes, usage=usage)

    async def generate_frame(self, project_id: str, description: str, orientation: str) -> AIResponseWrapper:
        model_id = "gemini-3-pro-image-preview"
        seed = self._get_project_seed(project_id)
        
        aspect_ratio = "16:9" if orientation == "16:9" else "9:16"
        
        response = self.client.models.generate_image(
            model=model_id,
            prompt=description,
            config=types.GenerateImageConfig(
                number_of_images=1,
                seed=seed,
                aspect_ratio=aspect_ratio
            )
        )
        
        # In a real scenario, we would upload the image bytes to GCS here.
        # For now, returning the generated image's internal reference or mock.
        image_url = response.generated_images[0].image_url if response.generated_images else "https://picsum.photos/800/450"
        
        usage = UsageMetrics(model_name=model_id, cost_usd=0.03) # Fixed cost for Image
        return AIResponseWrapper(data=image_url, usage=usage)

    async def generate_scene_video(self, project_id: str, scene: Scene) -> str:
        model_id = "veo-3.1-generate-preview"
        seed = self._get_project_seed(project_id)
        
        operation = self.client.models.generate_video(
            model=model_id,
            prompt=scene.visual_description,
            config=types.GenerateVideoConfig(
                duration_seconds=8,
                seed=seed
            )
        )
        
        # This is a long running operation. Operation.result() polls until finished.
        video = operation.result()
        return video.video_uri # Path to GCS

    async def stitch_production(self, project_id: str, scene_uris: List[str]) -> str:
        parent = f"projects/{self.project_id}/locations/us-central1"
        output_uri = f"gs://{self.project_id}-veogen-assets/productions/{project_id}/final.mp4"
        
        inputs = [transcoder_v1.types.Input(key=f"input{i}", uri=uri) for i, uri in enumerate(scene_uris)]
        edit_list = [
            transcoder_v1.types.EditAtom(key=f"atom{i}", inputs=[f"input{i}"], start_time_offset="0s")
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
                            bitrate_bps=5000000, frame_rate=30, height_pixels=720, width_pixels=1280
                        )
                    ),
                )
            ],
            mux_streams=[
                transcoder_v1.types.MuxStream(key="final", container="mp4", elementary_streams=["v1"])
            ],
        )

        response = self.transcoder_client.create_job(parent=parent, job=job)
        return output_uri
