import json
from google.cloud.video import transcoder_v1
from google.cloud import storage

class TranscoderService:
    def __init__(self, project_id: str, location: str):
        self.client = transcoder_v1.TranscoderServiceClient()
        self.project_id = project_id
        self.location = location
        self.parent = f"projects/{project_id}/locations/{location}"
        self.storage_client = storage.Client()

    def _read_manifest(self, gcs_uri: str) -> list:
        # gs://bucket/path/to/manifest.json
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

        # Create inputs
        inputs = []
        for i, uri in enumerate(video_uris):
            inputs.append(transcoder_v1.types.Input(key=f"input{i}", uri=uri))

        # Create edit list (sequencing)
        edit_list = []
        for i in range(len(video_uris)):
            edit_list.append(transcoder_v1.types.EditAtom(
                key=f"atom{i}",
                inputs=[f"input{i}"],
                start_time_offset="0s"
            ))

        job = transcoder_v1.types.Job()
        job.output_uri = output_uri
        job.config = transcoder_v1.types.JobConfig(
            inputs=inputs,
            edit_list=edit_list,
            elementary_streams=[
                transcoder_v1.types.ElementaryStream(
                    key="video_stream",
                    video_stream=transcoder_v1.types.VideoStream(
                        h264=transcoder_v1.types.VideoStream.H264CodecSettings(
                            bitrate_bps=5000000,
                            frame_rate=30,
                            height_pixels=720,
                            width_pixels=1280,
                        )
                    ),
                ),
                transcoder_v1.types.ElementaryStream(
                    key="audio_stream",
                    audio_stream=transcoder_v1.types.AudioStream(
                        codec="aac", bitrate_bps=128000
                    ),
                ),
            ],
            mux_streams=[
                transcoder_v1.types.MuxStream(
                    key="stitched_video",
                    container="mp4",
                    elementary_streams=["video_stream", "audio_stream"],
                )
            ],
        )

        response = self.client.create_job(parent=self.parent, job=job)
        return response.name

    def delete_job(self, job_name: str):
        try:
            self.client.delete_job(name=job_name)
        except Exception as e:
            print(f"Error deleting job: {e}")

    def get_job_status(self, job_name: str) -> str:
        try:
            job = self.client.get_job(name=job_name)
            return str(job.state.name)
        except Exception as e:
            return "UNKNOWN"
