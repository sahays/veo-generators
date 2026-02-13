import hashlib
from datetime import datetime
from fastapi import FastAPI, HTTPException, BackgroundTasks
from models import StitchRequest, JobStatus
from firestore_service import FirestoreService
from transcoder_service import TranscoderService

app = FastAPI(title="Veo Video Stitcher API")
firestore_svc = FirestoreService()

def get_job_id(manifest_uri: str, output_uri: str) -> str:
    hash_input = f"{manifest_uri}{output_uri}"
    return hashlib.sha256(hash_input.encode()).hexdigest()

@app.post("/jobs/start", response_model=JobStatus)
async def start_job(request: StitchRequest):
    job_id = get_job_id(request.manifest_gcs_uri, request.output_gcs_uri)
    existing_job = firestore_svc.get_job(job_id)

    if existing_job and existing_job.status in ["RUNNING", "SUCCEEDED"]:
        return existing_job

    transcoder_svc = TranscoderService(request.project_id, request.location)
    
    try:
        transcoder_job_name = transcoder_svc.create_stitch_job(
            request.manifest_gcs_uri, request.output_gcs_uri
        )
        
        job = JobStatus(
            job_id=job_id,
            status="RUNNING",
            manifest_gcs_uri=request.manifest_gcs_uri,
            output_gcs_uri=request.output_gcs_uri,
            transcoder_job_name=transcoder_job_name,
            last_updated=datetime.utcnow()
        )
        firestore_svc.update_job(job)
        return job
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/jobs/{job_id}/stop", response_model=JobStatus)
async def stop_job(job_id: str, project_id: str, location: str = "us-central1"):
    job = firestore_svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.transcoder_job_name:
        transcoder_svc = TranscoderService(project_id, location)
        transcoder_svc.delete_job(job.transcoder_job_name)

    job.status = "STOPPED"
    firestore_svc.update_job(job)
    return job

@app.post("/jobs/{job_id}/pause", response_model=JobStatus)
async def pause_job(job_id: str, project_id: str, location: str = "us-central1"):
    job = firestore_svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.transcoder_job_name:
        transcoder_svc = TranscoderService(project_id, location)
        transcoder_svc.delete_job(job.transcoder_job_name)

    job.status = "PAUSED"
    firestore_svc.update_job(job)
    return job

@app.post("/jobs/restart", response_model=JobStatus)
async def restart_job(request: StitchRequest):
    job_id = get_job_id(request.manifest_gcs_uri, request.output_gcs_uri)
    job = firestore_svc.get_job(job_id)
    
    transcoder_svc = TranscoderService(request.project_id, request.location)
    
    if job and job.transcoder_job_name:
        transcoder_svc.delete_job(job.transcoder_job_name)

    try:
        transcoder_job_name = transcoder_svc.create_stitch_job(
            request.manifest_gcs_uri, request.output_gcs_uri
        )
        
        new_job = JobStatus(
            job_id=job_id,
            status="RUNNING",
            manifest_gcs_uri=request.manifest_gcs_uri,
            output_gcs_uri=request.output_gcs_uri,
            transcoder_job_name=transcoder_job_name,
            last_updated=datetime.utcnow()
        )
        firestore_svc.update_job(new_job)
        return new_job
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/jobs/{job_id}/status", response_model=JobStatus)
async def get_status(job_id: str, project_id: str, location: str = "us-central1"):
    job = firestore_svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status == "RUNNING" and job.transcoder_job_name:
        transcoder_svc = TranscoderService(project_id, location)
        new_status = transcoder_svc.get_job_status(job.transcoder_job_name)
        if new_status != job.status:
            job.status = new_status
            firestore_svc.update_job(job)

    return job
