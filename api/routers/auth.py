import os
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

import deps
from models import InviteCode, CreateInviteCodeRequest, ValidateCodeRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

MASTER_INVITE_CODE = os.getenv("MASTER_INVITE_CODE", "")


def _get_master_code() -> str:
    return os.getenv("MASTER_INVITE_CODE", "")


def _is_master(code: str) -> bool:
    master = _get_master_code()
    return bool(master and code == master)


def _require_master(request: Request):
    code = request.headers.get("X-Invite-Code", "")
    if not _is_master(code):
        raise HTTPException(status_code=403, detail="Master access required")


def validate_code(code: str) -> dict:
    """Validate an invite code. Returns {valid, is_master}."""
    if _is_master(code):
        logger.info("Auth validate: master code accepted")
        return {"valid": True, "is_master": True}

    if not deps.firestore_svc:
        logger.warning("Auth validate: firestore service not available")
        return {"valid": False, "is_master": False}

    invite = deps.firestore_svc.get_invite_code_by_value(code)
    if not invite:
        logger.info("Auth validate: code not found in firestore")
        return {"valid": False, "is_master": False}

    if not invite.is_active:
        logger.info(f"Auth validate: code '{invite.label or invite.id}' is inactive")
        return {"valid": False, "is_master": False}

    if invite.expires_at and invite.expires_at.replace(
        tzinfo=invite.expires_at.tzinfo or timezone.utc
    ) < datetime.now(timezone.utc):
        logger.info(f"Auth validate: code '{invite.label or invite.id}' is expired")
        return {"valid": False, "is_master": False}

    logger.info(f"Auth validate: invite code '{invite.label or invite.id}' accepted")
    return {"valid": True, "is_master": False}


@router.post("/validate")
@deps.limiter.limit("5/minute")
async def validate(request: Request, body: ValidateCodeRequest):
    logger.info(f"Auth validate endpoint called, code length={len(body.code)}")
    return validate_code(body.code)


@router.get("/codes")
async def list_codes(request: Request):
    _require_master(request)
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service unavailable")
    codes = deps.firestore_svc.get_invite_codes()
    return [c.dict() for c in codes]


@router.post("/codes")
async def create_code(body: CreateInviteCodeRequest, request: Request):
    _require_master(request)
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service unavailable")

    existing = deps.firestore_svc.get_invite_code_by_value(body.code)
    if existing:
        raise HTTPException(status_code=409, detail="Code already exists")

    invite = InviteCode(
        code=body.code,
        label=body.label,
        expires_at=body.expires_at,
    )
    deps.firestore_svc.create_invite_code(invite)
    return invite.dict()


@router.post("/codes/{code_id}/revoke")
async def revoke_code(code_id: str, request: Request):
    _require_master(request)
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service unavailable")

    invite = deps.firestore_svc.get_invite_code(code_id)
    if not invite:
        raise HTTPException(status_code=404, detail="Code not found")

    deps.firestore_svc.update_invite_code(code_id, {"is_active": False})
    return {"status": "revoked"}


@router.post("/codes/{code_id}/activate")
async def activate_code(code_id: str, request: Request):
    _require_master(request)
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service unavailable")

    invite = deps.firestore_svc.get_invite_code(code_id)
    if not invite:
        raise HTTPException(status_code=404, detail="Code not found")

    deps.firestore_svc.update_invite_code(code_id, {"is_active": True})
    return {"status": "activated"}


@router.delete("/codes/{code_id}")
async def delete_code(code_id: str, request: Request):
    _require_master(request)
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service unavailable")

    invite = deps.firestore_svc.get_invite_code(code_id)
    if not invite:
        raise HTTPException(status_code=404, detail="Code not found")

    deps.firestore_svc.delete_invite_code(code_id)
    return {"status": "deleted"}
