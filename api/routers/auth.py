import os
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request

import deps
from models import InviteCode, CreateInviteCodeRequest, ValidateCodeRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

MASTER_INVITE_CODE = os.getenv("MASTER_INVITE_CODE", "")

# Default validity granted when promoting a code to power user. Power status
# reuses the code's own expiry, so promotion sets expires_at this far out.
POWER_DEFAULT_DAYS = 14


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
    """Validate an invite code. Returns {valid, is_master, is_power}.

    Master is a superset of power, so master codes report is_power=True too.
    Power status reuses the code's expiry, so an expired code is rejected
    outright (and therefore never reports is_power)."""
    if _is_master(code):
        logger.info("Auth validate: master code accepted")
        return {"valid": True, "is_master": True, "is_power": True}

    if not deps.firestore_svc:
        logger.warning("Auth validate: firestore service not available")
        return {"valid": False, "is_master": False, "is_power": False}

    invite = deps.firestore_svc.get_invite_code_by_value(code)
    if not invite:
        logger.info("Auth validate: code not found in firestore")
        return {"valid": False, "is_master": False, "is_power": False}

    if not invite.is_active:
        logger.info(f"Auth validate: code '{invite.label or invite.id}' is inactive")
        return {"valid": False, "is_master": False, "is_power": False}

    if invite.expires_at and invite.expires_at.replace(
        tzinfo=invite.expires_at.tzinfo or timezone.utc
    ) < datetime.now(timezone.utc):
        logger.info(f"Auth validate: code '{invite.label or invite.id}' is expired")
        return {"valid": False, "is_master": False, "is_power": False}

    logger.info(f"Auth validate: invite code '{invite.label or invite.id}' accepted")
    return {"valid": True, "is_master": False, "is_power": bool(invite.is_power)}


@router.post("/validate")
async def validate(request: Request, body: ValidateCodeRequest):
    logger.info(f"Auth validate endpoint called, code length={len(body.code)}")
    result = validate_code(body.code)
    return result


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
        daily_credits=body.daily_credits,
        expires_at=body.expires_at,
    )
    deps.firestore_svc.create_invite_code(invite)
    return invite.dict()


@router.patch("/codes/{code_id}")
async def update_code(code_id: str, body: dict, request: Request):
    _require_master(request)
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service unavailable")

    invite = deps.firestore_svc.get_invite_code(code_id)
    if not invite:
        raise HTTPException(status_code=404, detail="Code not found")

    updates = {}
    if "daily_credits" in body:
        val = body["daily_credits"]
        if not isinstance(val, int) or val < 1:
            raise HTTPException(
                status_code=400, detail="daily_credits must be a positive integer"
            )
        updates["daily_credits"] = val

    if "expires_at" in body:
        val = body["expires_at"]
        if val is None:
            updates["expires_at"] = None
        else:
            try:
                updates["expires_at"] = datetime.fromisoformat(
                    val.replace("Z", "+00:00")
                )
            except (ValueError, AttributeError):
                raise HTTPException(
                    status_code=400, detail="expires_at must be a valid ISO datetime"
                )

    if updates:
        deps.firestore_svc.update_invite_code(code_id, updates)
    return {"status": "updated"}


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


@router.post("/codes/{code_id}/promote")
async def promote_code(code_id: str, request: Request):
    """Promote an invite code to power user.

    Grants full feature access (everything except invite-code management) and
    sets a default 14-day expiry. Power status reuses the code's expiry, so it
    can be extended via the normal expiry-update flow and revoked via demote.
    """
    _require_master(request)
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service unavailable")

    invite = deps.firestore_svc.get_invite_code(code_id)
    if not invite:
        raise HTTPException(status_code=404, detail="Code not found")

    expires_at = datetime.now(timezone.utc) + timedelta(days=POWER_DEFAULT_DAYS)
    deps.firestore_svc.update_invite_code(
        code_id,
        {"is_power": True, "is_active": True, "expires_at": expires_at},
    )
    return {"status": "promoted", "expires_at": expires_at.isoformat()}


@router.post("/codes/{code_id}/demote")
async def demote_code(code_id: str, request: Request):
    """Revoke power-user status, returning the code to ordinary guest access.

    The code itself stays active and keeps its current expiry."""
    _require_master(request)
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service unavailable")

    invite = deps.firestore_svc.get_invite_code(code_id)
    if not invite:
        raise HTTPException(status_code=404, detail="Code not found")

    deps.firestore_svc.update_invite_code(code_id, {"is_power": False})
    return {"status": "demoted"}


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
