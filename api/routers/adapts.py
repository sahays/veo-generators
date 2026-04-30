import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import deps
from helpers import (
    list_image_upload_sources,
    require_firestore,
    sign_record_urls,
)
from models import AdaptRecord, AdaptVariant
from routers._crud import register_crud_routes

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


def _sign(record: AdaptRecord) -> dict:
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
    if deps.storage_svc and data.get("variants"):
        for variant in data["variants"]:
            gcs_uri = variant.get("output_gcs_uri")
            if gcs_uri:
                variant["output_signed_url"] = deps.storage_svc.get_signed_url(gcs_uri)
    return data


def _adapt_retry_updates(record: AdaptRecord) -> dict:
    """Custom retry: also reset failed variants to pending."""
    variants = [v.dict() for v in record.variants]
    for v in variants:
        if v["status"] == "failed":
            v["status"] = "pending"
            v["error_message"] = None
            v["output_gcs_uri"] = None
    return {
        "status": "pending",
        "error_message": None,
        "progress_pct": 0,
        "variants": variants,
    }


register_crud_routes(
    router,
    resource_label="Adapt record",
    getter=lambda rid: deps.firestore_svc.get_adapt_record(rid),
    updater=lambda rid, u: deps.firestore_svc.update_adapt_record(rid, u),
    deleter=lambda rid: deps.firestore_svc.delete_adapt_record(rid),
    lister=lambda include_archived=False: deps.firestore_svc.get_adapt_records(
        include_archived=include_archived
    ),
    sign_one=_sign,
    include_retry=True,
    retry_updates_fn=_adapt_retry_updates,
)


@router.get("/sources/uploads")
async def list_adapt_upload_sources():
    return list_image_upload_sources()


@router.get("/presets")
async def list_preset_bundles():
    return {"presets": PRESET_BUNDLES, "all_ratios": ALL_RATIOS}


@router.post("")
async def create_adapt(body: AdaptRequest, request: Request):
    """Create an adapt job. Worker picks it up from Firestore."""
    require_firestore()
    ratios = list(body.aspect_ratios)
    if body.preset_bundle and body.preset_bundle in PRESET_BUNDLES:
        ratios.extend(PRESET_BUNDLES[body.preset_bundle]["ratios"])
    seen = set()
    unique_ratios = []
    for r in ratios:
        if r not in seen and r in ALL_RATIOS:
            seen.add(r)
            unique_ratios.append(r)
    if not unique_ratios:
        raise HTTPException(400, "No valid aspect ratios selected")
    record = AdaptRecord(
        source_gcs_uri=body.gcs_uri,
        source_filename=body.source_filename,
        source_mime_type=body.source_mime_type,
        template_gcs_uri=body.template_gcs_uri or None,
        prompt_id=body.prompt_id,
        preset_bundle=body.preset_bundle,
        model_id=body.model_id,
        region=body.region,
        variants=[AdaptVariant(aspect_ratio=r) for r in unique_ratios],
        status="pending",
        invite_code=getattr(request.state, "invite_code", None),
    )
    deps.firestore_svc.create_adapt_record(record)
    return {"id": record.id, "status": record.status}
