"""UPI payment-intent and manual reference-review endpoints."""

import io
import os
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import urlencode

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db import PaymentRecord, get_session
from models.application import ApplicationDraft
from models.payment import UtrSubmitRequest

router = APIRouter(prefix="/payments", tags=["payments"])

UTR_PATTERN = re.compile(r"^\d{12}$")


class InitiatePaymentRequest(BaseModel):
    application: ApplicationDraft


def _payment_configuration() -> tuple[float, str, str, str]:
    vpa = os.getenv("UPI_VPA", "").strip()
    payee_name = os.getenv("UPI_PAYEE_NAME", "").strip()
    note = os.getenv("UPI_PAYMENT_NOTE", "Channel partner application fee").strip()
    if not vpa or not payee_name:
        raise HTTPException(status_code=503, detail="UPI payment details are not configured.")
    try:
        amount = float(os.getenv("APPLICATION_FEE_INR", "299"))
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="The application fee configuration is invalid.") from exc
    if amount <= 0:
        raise HTTPException(status_code=503, detail="The application fee configuration is invalid.")
    return amount, vpa, payee_name, note


def _upi_link(vpa: str, payee_name: str, amount: float, note: str) -> str:
    return "upi://pay?" + urlencode(
        {
            "pa": vpa,
            "pn": payee_name,
            "am": f"{amount:.2f}",
            "cu": "INR",
            "tn": note,
        }
    )


async def _create_payment(session: AsyncSession, application: dict) -> dict:
    amount, vpa, payee_name, base_note = _payment_configuration()
    payment_id = str(uuid.uuid4())
    note = f"{base_note} {payment_id[:8]}"
    payment = PaymentRecord(
        id=payment_id,
        amount=amount,
        currency="INR",
        status="pending",
        upi_vpa=vpa,
        payee_name=payee_name,
        upi_note=note,
        upi_link=_upi_link(vpa, payee_name, amount, note),
        application=application,
        created_at=datetime.now(timezone.utc),
    )
    session.add(payment)
    await session.commit()
    return {
        **_payment_dict(payment),
        "applicant_name": application.get("full_name"),
    }


def _payment_dict(payment: PaymentRecord) -> dict:
    return {
        "id": payment.id,
        "amount": payment.amount,
        "currency": payment.currency,
        "status": payment.status,
        "upi_vpa": payment.upi_vpa,
        "payee_name": payment.payee_name,
        "upi_note": payment.upi_note,
        "upi_link": payment.upi_link,
        "utr": payment.utr,
        "created_at": payment.created_at,
        "verified_at": payment.verified_at,
    }


@router.post("/initiate", status_code=201)
async def initiate_payment(
    request: InitiatePaymentRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Create a pending UPI intent; this does not confirm or collect payment."""
    return await _create_payment(session, request.application.model_dump())


@router.get("/{payment_id}")
async def get_payment(payment_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    payment = await session.get(PaymentRecord, payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment session not found.")
    return {**_payment_dict(payment), "applicant_name": payment.application.get("full_name")}


@router.get("/{payment_id}/qr.svg")
async def get_payment_qr(payment_id: str, session: AsyncSession = Depends(get_session)) -> Response:
    payment = await session.get(PaymentRecord, payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment session not found.")
    image = qrcode.make(
        payment.upi_link,
        image_factory=qrcode.image.svg.SvgPathImage,
        box_size=8,
        border=3,
    )
    output = io.BytesIO()
    image.save(output)
    return Response(content=output.getvalue(), media_type="image/svg+xml")


@router.post("/{payment_id}/verify")
async def submit_payment_reference(
    payment_id: str,
    request: UtrSubmitRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Record a UTR for review. Format validation is not proof of payment."""
    payment = await session.get(PaymentRecord, payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment session not found.")
    if payment.status == "verified":
        return _payment_dict(payment)
    if payment.status == "pending_review":
        if payment.utr == request.utr:
            return _payment_dict(payment)
        raise HTTPException(status_code=409, detail="This payment reference is already awaiting review.")
    if payment.status != "pending":
        raise HTTPException(status_code=409, detail="This payment cannot accept a reference. Start a retry.")
    if not UTR_PATTERN.fullmatch(request.utr):
        raise HTTPException(status_code=422, detail="Enter the 12-digit UPI reference from your receipt.")

    try:
        result = await session.execute(
            update(PaymentRecord)
            .where(PaymentRecord.id == payment_id, PaymentRecord.status == "pending")
            .values(
                utr=request.utr,
                status="pending_review",
                utr_submitted_at=datetime.now(timezone.utc),
            )
            .returning(PaymentRecord)
        )
        updated = result.scalar_one_or_none()
        if updated is None:
            await session.rollback()
            raise HTTPException(status_code=409, detail="Payment status changed. Refresh and try again.")
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="That UPI reference has already been submitted.") from exc
    return _payment_dict(updated)


@router.post("/{payment_id}/fail")
async def report_payment_failure(payment_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    result = await session.execute(
        update(PaymentRecord)
        .where(PaymentRecord.id == payment_id, PaymentRecord.status == "pending")
        .values(status="failed", failed_at=datetime.now(timezone.utc))
        .returning(PaymentRecord)
    )
    payment = result.scalar_one_or_none()
    if payment is None:
        payment = await session.get(PaymentRecord, payment_id)
        if payment is None:
            raise HTTPException(status_code=404, detail="Payment session not found.")
        if payment.status == "pending_review":
            raise HTTPException(status_code=409, detail="This payment reference is awaiting manual review.")
        if payment.status != "failed":
            raise HTTPException(status_code=409, detail="This payment can no longer be marked failed.")
        return _payment_dict(payment)
    await session.commit()
    return _payment_dict(payment)


@router.post("/{payment_id}/retry", status_code=201)
async def retry_payment(payment_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    previous = await session.get(PaymentRecord, payment_id)
    if previous is None:
        raise HTTPException(status_code=404, detail="Payment session not found.")
    if previous.status != "failed":
        raise HTTPException(status_code=409, detail="Only a failed payment can be retried.")
    return await _create_payment(session, previous.application)
