"""Authentication and invite-code management endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request

import deps
from models import CreateInviteCodeRequest, InviteCode, ValidateCodeRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

MASTER_INVITE_CODE = os.getenv("MASTER_INVITE_CODE", "")

# Default validity granted when promoting a code to power user. Power status
# reuses the code's own expiry, so promotion sets expires_at this far out.
POWER_DEFAULT_DAYS = 14


def _auth_log(where: str, what: str, why: str, how: str) -> dict[str, str]:
    """Build structured 5W1H telemetry context for auth events."""
    return {"who": "auth_router", "where": where, "what": what, "why": why, "how": how}


def _get_master_code() -> str:
    """Read the master invite code from environment."""
    return os.getenv("MASTER_INVITE_CODE", "")


def _is_master(code: str) -> bool:
    """Return True if `code` matches the configured master invite code."""
    master = _get_master_code()
    return bool(master and code == master)


def _require_master(request: Request) -> None:
    """Raise 403 unless the request carries the master invite code."""
    code = request.headers.get("X-Invite-Code", "")
    if not _is_master(code):
        raise HTTPException(status_code=403, detail="Master access required")


def _require_invite_or_404(code_id: str, request: Request) -> Any:
    """Verify master access, ensure Firestore is available, and fetch invite code."""
    _require_master(request)
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service unavailable")
    invite = deps.firestore_svc.get_invite_code(code_id)
    if not invite:
        raise HTTPException(status_code=404, detail="Code not found")
    return invite


def _is_invite_expired(invite: Any) -> bool:
    """Return True if an invite code has an `expires_at` timestamp in the past."""
    if not invite.expires_at:
        return False
    exp = invite.expires_at.replace(tzinfo=invite.expires_at.tzinfo or timezone.utc)
    return exp < datetime.now(timezone.utc)


def validate_code(code: str) -> dict[str, bool]:
    """Validate an invite code. Returns {valid, is_master, is_power}."""
    if _is_master(code):
        logger.info(
            "Auth validate: master code accepted",
            extra=_auth_log(
                "validate_code", "master_accepted", "matched_env", "direct_check"
            ),
        )
        return {"valid": True, "is_master": True, "is_power": True}
    if not deps.firestore_svc:
        logger.warning(
            "Auth validate: firestore service not available",
            extra=_auth_log(
                "validate_code", "firestore_unavailable", "no_svc", "reject"
            ),
        )
        return {"valid": False, "is_master": False, "is_power": False}
    invite = deps.firestore_svc.get_invite_code_by_value(code)
    if not invite:
        logger.info(
            "Auth validate: code not found in firestore",
            extra=_auth_log("validate_code", "code_not_found", "missing_doc", "reject"),
        )
        return {"valid": False, "is_master": False, "is_power": False}
    label = invite.label or invite.id
    if not invite.is_active:
        logger.info(
            f"Auth validate: code '{label}' is inactive",
            extra=_auth_log("validate_code", "code_inactive", str(label), "reject"),
        )
        return {"valid": False, "is_master": False, "is_power": False}
    if _is_invite_expired(invite):
        logger.info(
            f"Auth validate: code '{label}' is expired",
            extra=_auth_log("validate_code", "code_expired", str(label), "reject"),
        )
        return {"valid": False, "is_master": False, "is_power": False}
    logger.info(
        f"Auth validate: invite code '{label}' accepted",
        extra=_auth_log(
            "validate_code", "invite_accepted", str(label), "firestore_lookup"
        ),
    )
    return {"valid": True, "is_master": False, "is_power": bool(invite.is_power)}


@router.post("/validate")
async def validate(request: Request, body: ValidateCodeRequest) -> dict[str, bool]:
    """Validate an invite code from request body."""
    _ = request
    logger.info(
        f"Auth validate endpoint called, code length={len(body.code)}",
        extra=_auth_log(
            "validate", "validate_called", f"len={len(body.code)}", "post_validate"
        ),
    )
    return validate_code(body.code)


@router.get("/codes")
async def list_codes(request: Request) -> list[dict[str, Any]]:
    """List all invite codes (master access required)."""
    _require_master(request)
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service unavailable")
    codes = deps.firestore_svc.get_invite_codes()
    return [c.dict() for c in codes]


@router.post("/codes")
async def create_code(
    body: CreateInviteCodeRequest, request: Request
) -> dict[str, Any]:
    """Create a new invite code (master access required)."""
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


def _parse_code_updates(body: dict[str, Any]) -> dict[str, Any]:
    """Validate and extract `daily_credits` and `expires_at` fields from PATCH body."""
    updates: dict[str, Any] = {}
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
    return updates


@router.patch("/codes/{code_id}")
async def update_code(
    code_id: str, body: dict[str, Any], request: Request
) -> dict[str, str]:
    """Update daily credits or expiry timestamp of an invite code."""
    _require_invite_or_404(code_id, request)
    updates = _parse_code_updates(body)
    if updates:
        deps.firestore_svc.update_invite_code(code_id, updates)
    return {"status": "updated"}


@router.post("/codes/{code_id}/revoke")
async def revoke_code(code_id: str, request: Request) -> dict[str, str]:
    """Deactivate an invite code."""
    _require_invite_or_404(code_id, request)
    deps.firestore_svc.update_invite_code(code_id, {"is_active": False})
    return {"status": "revoked"}


@router.post("/codes/{code_id}/activate")
async def activate_code(code_id: str, request: Request) -> dict[str, str]:
    """Re-activate an invite code."""
    _require_invite_or_404(code_id, request)
    deps.firestore_svc.update_invite_code(code_id, {"is_active": True})
    return {"status": "activated"}


@router.post("/codes/{code_id}/promote")
async def promote_code(code_id: str, request: Request) -> dict[str, str]:
    """Promote an invite code to power user with a 14-day default expiry."""
    _require_invite_or_404(code_id, request)
    expires_at = datetime.now(timezone.utc) + timedelta(days=POWER_DEFAULT_DAYS)
    deps.firestore_svc.update_invite_code(
        code_id, {"is_power": True, "is_active": True, "expires_at": expires_at}
    )
    return {"status": "promoted", "expires_at": expires_at.isoformat()}


@router.post("/codes/{code_id}/demote")
async def demote_code(code_id: str, request: Request) -> dict[str, str]:
    """Revoke power-user status, returning the code to ordinary guest access."""
    _require_invite_or_404(code_id, request)
    deps.firestore_svc.update_invite_code(code_id, {"is_power": False})
    return {"status": "demoted"}


@router.delete("/codes/{code_id}")
async def delete_code(code_id: str, request: Request) -> dict[str, str]:
    """Permanently delete an invite code."""
    _require_invite_or_404(code_id, request)
    deps.firestore_svc.delete_invite_code(code_id)
    return {"status": "deleted"}
