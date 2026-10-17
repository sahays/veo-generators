import json
import logging
import os
from typing import Any
from google.cloud.video import transcoder_v1
from google.cloud import storage

logger = logging.getLogger(__name__)


def _build_audio_elementary_stream(
    key: str = "audio_stream",
) -> transcoder_v1.types.ElementaryStream:
    return transcoder_v1.types.ElementaryStream(
        key=key,
        audio_stream=transcoder_v1.types.AudioStream(codec="aac", bitrate_bps=128000),
    )


def _build_h264_elementary_stream(
    key: str,
    width: int,
    height: int,
    bitrate_bps: int,
    frame_rate: float = 30,
    **extra: Any,
) -> transcoder_v1.types.ElementaryStream:
    return transcoder_v1.types.ElementaryStream(
        key=key,
        video_stream=transcoder_v1.types.VideoStream(
            h264=transcoder_v1.types.VideoStream.H264CodecSettings(
                width_pixels=width,
                height_pixels=height,
                bitrate_bps=bitrate_bps,
                frame_rate=frame_rate,
                **extra,
            )
        ),
    )


def _resolve_stitch_dimensions(
    resolution: str, orientation: str
) -> tuple[int, int, int, str]:
    if resolution == "360p":
        base_w, base_h, bitrate_bps, mux_key = 640, 360, 1500000, "draft"
    elif resolution == "1080p":
        base_w, base_h, bitrate_bps, mux_key = 1920, 1080, 8000000, "final"
    else:
        base_w, base_h, bitrate_bps, mux_key = 1280, 720, 5000000, "final"
    width, height = (base_h, base_w) if orientation == "9:16" else (base_w, base_h)
    return width, height, bitrate_bps, mux_key


class TranscoderService:
    def __init__(self, project_id: str | None, location: str) -> None:
        self.client = transcoder_v1.TranscoderServiceClient()
        self.project_id = project_id
        self.location = location
        self.parent = f"projects/{project_id}/locations/{location}"
        self.storage_client = storage.Client()

    def _read_manifest(self, gcs_uri: str) -> list:
        parts = gcs_uri.replace("gs://", "").split("/", 1)
        bucket_name = parts[0]
        blob_name = parts[1]
        bucket = self.storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        content = blob.download_as_text()
        data = json.loads(content)
        return data.get("videos", [])

    def create_stitch_job(self, manifest_uri: str, output_uri: str) -> str:
        video_uris = self._read_manifest(manifest_uri)
        if not video_uris:
            raise ValueError("Manifest is empty or invalid")
        inputs = [
            transcoder_v1.types.Input(key=f"input{i}", uri=uri)
            for i, uri in enumerate(video_uris)
        ]
        edit_list = [
            transcoder_v1.types.EditAtom(
                key=f"atom{i}", inputs=[f"input{i}"], start_time_offset="0s"
            )
            for i in range(len(video_uris))
        ]
        job = transcoder_v1.types.Job()
        job.output_uri = output_uri
        job.config = transcoder_v1.types.JobConfig(
            inputs=inputs,
            edit_list=edit_list,
            elementary_streams=[
                _build_h264_elementary_stream("video_stream", 1280, 720, 5000000),
                _build_audio_elementary_stream("audio_stream"),
            ],
            mux_streams=[
                transcoder_v1.types.MuxStream(
                    key="stitched_video",
                    container="mp4",
                    elementary_streams=["video_stream", "audio_stream"],
                )
            ],
        )
        return self.client.create_job(parent=self.parent, job=job).name

    def delete_job(self, job_name: str) -> None:
        try:
            self.client.delete_job(name=job_name)
        except Exception as e:
            logger.warning(
                f"Error deleting job: {e}",
                extra={
                    "who": "transcoder_service",
                    "where": "delete_job",
                    "what": "delete_job_failed",
                    "why": str(e),
                    "how": job_name,
                },
            )

    def stitch_from_uris(
        self,
        production_id: str,
        scene_uris: list,
        orientation: str = "16:9",
        resolution: str = "720p",
    ) -> tuple:
        """Stitch a list of GCS video URIs into a single final or draft video."""
        bucket = os.getenv("GCS_BUCKET")
        output_uri = f"gs://{bucket}/productions/{production_id}/stitched/"
        width, height, bitrate_bps, mux_key = _resolve_stitch_dimensions(
            resolution, orientation
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
                _build_h264_elementary_stream("v1", width, height, bitrate_bps),
                _build_audio_elementary_stream("a1"),
            ],
            mux_streams=[
                transcoder_v1.types.MuxStream(
                    key=mux_key, container="mp4", elementary_streams=["v1", "a1"]
                )
            ],
        )
        created_job = self.client.create_job(parent=self.parent, job=job)
        return (created_job.name, f"{output_uri}{mux_key}.mp4")

    def compress_video(self, upload_id: str, input_uri: str, resolution: str) -> tuple:
        """Compress a video to a lower resolution. Returns (job_name, output_gcs_uri)."""
        bucket = os.getenv("GCS_BUCKET")
        output_uri = f"gs://{bucket}/uploads/compressed/{upload_id}/{resolution}/"
        presets = {
            "480p": {"width": 854, "height": 480, "crf": 26, "bitrate_bps": 2000000},
            "720p": {"width": 1280, "height": 720, "crf": 23, "bitrate_bps": 5000000},
        }
        p = presets[resolution]
        v_stream = _build_h264_elementary_stream(
            "video_stream",
            p["width"],
            p["height"],
            p["bitrate_bps"],
            crf_level=p["crf"],
            rate_control_mode="crf",
            profile="high",
            preset="slow",
            b_frame_count=3,
            entropy_coder="cabac",
        )
        job = transcoder_v1.types.Job()
        job.input_uri = input_uri
        job.output_uri = output_uri
        job.config = transcoder_v1.types.JobConfig(
            elementary_streams=[
                v_stream,
                _build_audio_elementary_stream("audio_stream"),
            ],
            mux_streams=[
                transcoder_v1.types.MuxStream(
                    key="compressed",
                    container="mp4",
                    elementary_streams=["video_stream", "audio_stream"],
                )
            ],
        )
        created_job = self.client.create_job(parent=self.parent, job=job)
        return (created_job.name, f"{output_uri}compressed.mp4")

    def reframe_encode(
        self,
        record_id: str,
        input_uri: str,
        has_audio: bool = True,
        blurred_bg: bool = False,
        out_h: int = 1920,
        fps: float = 0.0,
    ) -> tuple:
        """Encode a reframed video. Returns (job_name, output_gcs_uri)."""
        bucket = os.getenv("GCS_BUCKET")
        output_uri = f"gs://{bucket}/reframes/{record_id}/encoded/"
        v_stream = _build_h264_elementary_stream(
            "video_stream",
            1080,
            out_h,
            8000000,
            frame_rate=fps or 30,
            crf_level=18,
            rate_control_mode="crf",
            profile="high",
            preset="slow",
            b_frame_count=3,
            entropy_coder="cabac",
        )
        elementary_streams = [v_stream]
        mux_elementary = ["video_stream"]
        if has_audio:
            elementary_streams.append(_build_audio_elementary_stream("audio_stream"))
            mux_elementary.append("audio_stream")
        job = transcoder_v1.types.Job()
        job.input_uri = input_uri
        job.output_uri = output_uri
        job.config = transcoder_v1.types.JobConfig(
            elementary_streams=elementary_streams,
            mux_streams=[
                transcoder_v1.types.MuxStream(
                    key="reframed", container="mp4", elementary_streams=mux_elementary
                )
            ],
        )
        created_job = self.client.create_job(parent=self.parent, job=job)
        return (created_job.name, f"{output_uri}reframed.mp4")

    def get_job_status(self, job_name: str) -> str:
        try:
            job = self.client.get_job(name=job_name)
            return str(job.state.name)
        except Exception:
            return "UNKNOWN"
