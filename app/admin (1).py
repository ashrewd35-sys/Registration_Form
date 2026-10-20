"""PIN-protected manual payment review endpoints."""

import hashlib
import hmac
import os
import secrets
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db import ApplicationRecord, PaymentRecord, get_session

router = APIRouter(prefix="/admin", tags=["admin"])
SESSION_SECONDS = 8 * 60 * 60


class AdminLoginRequest(BaseModel):
    pin: str = Field(min_length=1, max_length=128)


def _session_token(pin: str, issued_at: int, nonce: str) -> str:
    payload = f"{issued_at}.{nonce}"
    signature = hmac.new(pin.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def _require_admin(authorization: str | None = Header(default=None)) -> str:
    configured_pin = os.getenv("ADMIN_PIN", "")
    if not configured_pin:
        raise HTTPException(status_code=503, detail="Admin access is not configured.")
    if len(configured_pin) < 16:
        raise HTTPException(status_code=503, detail="Admin access requires an ADMIN_PIN of at least 16 characters.")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Admin sign-in is required.")
    parts = authorization[7:].split(".")
    if len(parts) != 3:
        raise HTTPException(status_code=401, detail="Admin session is invalid.")
    issued_text, nonce, signature = parts
    try:
        issued_at = int(issued_text)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Admin session is invalid.") from exc
    now = int(time.time())
    if issued_at > now + 60 or now - issued_at > SESSION_SECONDS:
        raise HTTPException(status_code=401, detail="Admin session has expired.")
    expected = _session_token(configured_pin, issued_at, nonce).rsplit(".", 1)[1]
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="Admin session is invalid.")
    return configured_pin


@router.post("/login")
async def admin_login(request: AdminLoginRequest) -> dict:
    configured_pin = os.getenv("ADMIN_PIN", "")
    if not configured_pin:
        raise HTTPException(status_code=503, detail="Admin access is not configured.")
    if len(configured_pin) < 16:
        raise HTTPException(status_code=503, detail="Admin access requires an ADMIN_PIN of at least 16 characters.")
    if not hmac.compare_digest(request.pin.encode("utf-8"), configured_pin.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Incorrect admin PIN.")
    issued_at = int(time.time())
    nonce = secrets.token_urlsafe(18)
    return {"token": _session_token(configured_pin, issued_at, nonce), "expires_in": SESSION_SECONDS}


@router.get("/payments")
async def list_payments(
    _: str = Depends(_require_admin),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    rows = (
        await session.scalars(select(PaymentRecord).order_by(PaymentRecord.created_at.desc()).limit(500))
    ).all()
    return [
        {
            "id": row.id,
            "amount": row.amount,
            "currency": row.currency,
            "status": row.status,
            "upi_vpa": row.upi_vpa,
            "utr": row.utr,
            "created_at": row.created_at,
            "verified_at": row.verified_at,
            "applicant_name": row.application.get("full_name"),
            "applicant_phone": row.application.get("phone"),
        }
        for row in rows
    ]


@router.get("/applications")
async def list_applications(
    _: str = Depends(_require_admin),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    rows = (
        await session.scalars(
            select(ApplicationRecord).order_by(ApplicationRecord.created_at.desc()).limit(500)
        )
    ).all()
    return [
        {
            "id": row.id,
            "reference_no": row.reference_no,
            "status": row.status,
            "payment_id": row.payment_id,
            "payment_utr": row.payment_utr,
            "full_name": row.full_name,
            "phone": row.phone,
            "whatsapp": row.whatsapp,
            "email": row.email,
            "district": row.district,
            "professions": row.professions,
            "has_shop": row.has_shop,
            "experience": row.experience,
            "comments": row.comments,
            "created_at": row.created_at,
            "confirmed_at": row.confirmed_at,
        }
        for row in rows
    ]


@router.post("/payments/{payment_id}/confirm")
async def confirm_payment(
    payment_id: str,
    _: str = Depends(_require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    result = await session.execute(
        update(PaymentRecord)
        .where(
            PaymentRecord.id == payment_id,
            PaymentRecord.status == "pending_review",
            PaymentRecord.utr.is_not(None),
        )
        .values(status="verified", verified_at=datetime.now(timezone.utc))
        .returning(PaymentRecord)
    )
    payment = result.scalar_one_or_none()
    if payment is None:
        payment = await session.get(PaymentRecord, payment_id)
        if payment is None:
            raise HTTPException(status_code=404, detail="Payment session not found.")
        raise HTTPException(status_code=409, detail="Only a payment awaiting review can be confirmed.")
    await session.commit()
    return {
        "id": payment.id,
        "status": payment.status,
        "utr": payment.utr,
        "verified_at": payment.verified_at,
    }


@router.post("/payments/{payment_id}/reject")
async def reject_payment(
    payment_id: str,
    _: str = Depends(_require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    result = await session.execute(
        update(PaymentRecord)
        .where(PaymentRecord.id == payment_id, PaymentRecord.status == "pending_review")
        .values(status="failed", failed_at=datetime.now(timezone.utc))
        .returning(PaymentRecord)
    )
    payment = result.scalar_one_or_none()
    if payment is None:
        payment = await session.get(PaymentRecord, payment_id)
        if payment is None:
            raise HTTPException(status_code=404, detail="Payment session not found.")
        raise HTTPException(status_code=409, detail="Only a payment awaiting review can be rejected.")
    await session.commit()
    return {"id": payment.id, "status": payment.status, "utr": payment.utr}
