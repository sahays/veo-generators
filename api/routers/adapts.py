import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import deps
from helpers import (
    get_or_404,
    list_image_upload_sources,
    require_firestore,
    sign_record_urls,
)
from models import AdaptRecord, AdaptVariant

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/adapts", tags=["adapts"])

PRESET_BUNDLES = {
    "ott": {"name": "OTT Platform", "ratios": ["16:9", "9:16", "1:1", "4:3"]},
    "social": {"name": "Social Media", "ratios": ["4:5", "1:1", "9:16"]},
    "print": {"name": "Print", "ratios": ["3:4", "4:3", "1:1"]},
    "ultrawide": {"name": "Ultra Wide", "ratios": ["21:9", "8:1", "4:1"]},
}

ALL_RATIOS = [
    "1:1",
    "16:9",
    "9:16",
    "4:3",
    "3:4",
    "4:5",
    "5:4",
    "2:3",
    "3:2",
    "21:9",
    "1:4",
    "4:1",
    "1:8",
    "8:1",
]


class AdaptRequest(BaseModel):
    gcs_uri: str
    source_filename: str = ""
    source_mime_type: str = "image/png"
    template_gcs_uri: str = ""
    prompt_id: str = ""
    preset_bundle: str = ""
    aspect_ratios: list[str] = []
    model_id: Optional[str] = None
    region: Optional[str] = None


def _sign_adapt_urls(record: AdaptRecord) -> dict:
    uri_fields = {"source_gcs_uri": "source_signed_url"}
    if record.template_gcs_uri:
        uri_fields["template_gcs_uri"] = "template_signed_url"
    data = sign_record_urls(
        record,
        uri_fields,
        lambda cache: deps.firestore_svc.update_adapt_record(
            record.id, {"signed_urls": cache}
        ),
    )
    # Sign variant output URIs
    if deps.storage_svc and data.get("variants"):
        for variant in data["variants"]:
            gcs_uri = variant.get("output_gcs_uri")
            if gcs_uri:
                variant["output_signed_url"] = deps.storage_svc.get_signed_url(gcs_uri)
    return data


@router.get("")
async def list_adapts(request: Request, archived: bool = False):
    require_firestore()
    records = deps.firestore_svc.get_adapt_records(include_archived=archived)
    return [_sign_adapt_urls(r) for r in records]


@router.get("/sources/uploads")
async def list_adapt_upload_sources():
    """List uploaded images that can be adapted."""
    return list_image_upload_sources()


@router.get("/presets")
async def list_preset_bundles():
    """Return available aspect ratio preset bundles."""
    return {
        "presets": PRESET_BUNDLES,
        "all_ratios": ALL_RATIOS,
    }


@router.get("/{record_id}")
async def get_adapt(record_id: str):
    require_firestore()
    record = get_or_404(deps.firestore_svc.get_adapt_record, record_id, "Adapt record")
    return _sign_adapt_urls(record)


@router.post("")
async def create_adapt(body: AdaptRequest, request: Request):
    """Create an adapt job. Worker picks it up from Firestore."""
    require_firestore()

    # Resolve aspect ratios from preset + explicit list
    ratios = list(body.aspect_ratios)
    if body.preset_bundle and body.preset_bundle in PRESET_BUNDLES:
        ratios.extend(PRESET_BUNDLES[body.preset_bundle]["ratios"])

    # Deduplicate while preserving order
    seen = set()
    unique_ratios = []
    for r in ratios:
        if r not in seen and r in ALL_RATIOS:
            seen.add(r)
            unique_ratios.append(r)

    if not unique_ratios:
        raise HTTPException(400, "No valid aspect ratios selected")

    variants = [AdaptVariant(aspect_ratio=r) for r in unique_ratios]

    record = AdaptRecord(
        source_gcs_uri=body.gcs_uri,
        source_filename=body.source_filename,
        source_mime_type=body.source_mime_type,
        template_gcs_uri=body.template_gcs_uri or None,
        prompt_id=body.prompt_id,
        preset_bundle=body.preset_bundle,
        model_id=body.model_id,
        region=body.region,
        variants=variants,
        status="pending",
        invite_code=getattr(request.state, "invite_code", None),
    )
    deps.firestore_svc.create_adapt_record(record)

    return {"id": record.id, "status": record.status}


@router.post("/{record_id}/retry")
async def retry_adapt(record_id: str):
    """Reset a failed/partial adapt to pending so the worker retries."""
    require_firestore()
    record = get_or_404(deps.firestore_svc.get_adapt_record, record_id, "Adapt record")
    if record.status in ("pending", "completed"):
        raise HTTPException(400, f"Cannot retry a {record.status} adapt")

    # Reset failed variants to pending
    variants = [v.dict() for v in record.variants]
    for v in variants:
        if v["status"] == "failed":
            v["status"] = "pending"
            v["error_message"] = None
            v["output_gcs_uri"] = None

    deps.firestore_svc.update_adapt_record(
        record_id,
        {
            "status": "pending",
            "error_message": None,
            "progress_pct": 0,
            "variants": variants,
        },
    )
    return {"id": record_id, "status": "pending"}


@router.patch("/{record_id}")
async def update_adapt(record_id: str, body: dict):
    require_firestore()
    get_or_404(deps.firestore_svc.get_adapt_record, record_id, "Adapt record")
    updates = {}
    if "display_name" in body:
        updates["display_name"] = str(body["display_name"]).strip()
    if not updates:
        raise HTTPException(400, "No valid fields to update")
    deps.firestore_svc.update_adapt_record(record_id, updates)
    return {"status": "updated"}


@router.post("/{record_id}/archive")
async def archive_adapt(record_id: str):
    require_firestore()
    get_or_404(deps.firestore_svc.get_adapt_record, record_id, "Adapt record")
    deps.firestore_svc.update_adapt_record(record_id, {"archived": True})
    return {"status": "archived"}


@router.delete("/{record_id}")
async def delete_adapt(record_id: str):
    require_firestore()
    get_or_404(deps.firestore_svc.get_adapt_record, record_id, "Adapt record")
    deps.firestore_svc.delete_adapt_record(record_id)
    return {"status": "deleted"}
