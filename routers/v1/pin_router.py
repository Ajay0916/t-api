"""API PIN rotation and emergency-reset endpoints."""

from __future__ import annotations

import asyncio
import hmac
import os
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from helper.dependencies import authenticate_request
from helper.logging_setup import get_logger
from helper.pin_manager import set_active_pin, state_exists, verify_active_pin

router = APIRouter(tags=["PIN"])
LOGGER = get_logger("tapi.pin")

MAX_ATTEMPTS = 5
ATTEMPT_WINDOW = 60.0
LOCK_SECONDS = 60.0
_attempts: dict[str, deque[float]] = defaultdict(deque)
_attempt_lock = asyncio.Lock()


class PinChangeRequest(BaseModel):
    current_pin: str
    new_pin: str
    confirm_new_pin: str


class PinResetRequest(BaseModel):
    reset_pin: str
    new_pin: str
    confirm_new_pin: str


async def _check_rate_limit(key: str) -> None:
    now = time.monotonic()
    async with _attempt_lock:
        attempts = _attempts[key]
        while attempts and now - attempts[0] >= ATTEMPT_WINDOW + LOCK_SECONDS:
            attempts.popleft()
        recent = [stamp for stamp in attempts if now - stamp < ATTEMPT_WINDOW]
        if len(recent) >= MAX_ATTEMPTS and now - recent[-1] < LOCK_SECONDS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many attempts. Try again later.",
            )


async def _record_attempt(key: str, success: bool) -> None:
    now = time.monotonic()
    async with _attempt_lock:
        if success:
            _attempts.pop(key, None)
            return
        attempts = _attempts[key]
        attempts.append(now)
        while attempts and now - attempts[0] >= ATTEMPT_WINDOW + LOCK_SECONDS:
            attempts.popleft()


def _validate_new_pin(new_pin: str, confirm_pin: str, forbidden_pin: str | None = None) -> str:
    if len(new_pin) < 2 or len(new_pin) > 128:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="PIN must be between 2 and 128 characters.",
        )
    if not hmac.compare_digest(new_pin, confirm_pin):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New PIN confirmation does not match.",
        )
    if forbidden_pin and hmac.compare_digest(new_pin, forbidden_pin):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New PIN must be different.",
        )
    return new_pin


@router.post("/change", dependencies=[Depends(authenticate_request)])
async def change_pin(request: Request, payload: PinChangeRequest):
    client_ip = request.client.host if request.client else "unknown"
    rate_key = f"change:{client_ip}"
    await _check_rate_limit(rate_key)

    current_pin = payload.current_pin.strip()
    new_pin = payload.new_pin.strip()
    confirm_pin = payload.confirm_new_pin.strip()

    if not state_exists() or not verify_active_pin(current_pin):
        await _record_attempt(rate_key, success=False)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Current PIN is incorrect.",
        )

    validated_pin = _validate_new_pin(new_pin, confirm_pin, current_pin)
    set_active_pin(validated_pin)
    await _record_attempt(rate_key, success=True)
    LOGGER.info("API PIN changed")
    return {"status": "ok", "message": "PIN updated."}


@router.post("/reset")
async def reset_pin(request: Request, payload: PinResetRequest):
    master_pin = os.getenv("TAPI_MASTER_PIN", "")
    if not master_pin:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PIN reset is not configured.",
        )

    client_ip = request.client.host if request.client else "unknown"
    rate_key = f"reset:{client_ip}"
    await _check_rate_limit(rate_key)

    supplied_master = payload.reset_pin.strip()
    if not hmac.compare_digest(supplied_master, master_pin):
        await _record_attempt(rate_key, success=False)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Reset PIN is incorrect.",
        )

    new_pin = payload.new_pin.strip()
    confirm_pin = payload.confirm_new_pin.strip()
    validated_pin = _validate_new_pin(new_pin, confirm_pin, master_pin)
    set_active_pin(validated_pin)
    await _record_attempt(rate_key, success=True)
    LOGGER.info("API PIN reset with master PIN")
    return {"status": "ok", "message": "PIN updated."}
