"""Application submission, permitted only after an admin verifies payment."""

import secrets
import string
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db import ApplicationRecord, PaymentRecord, get_session
from models.application import ApplicationSubmitRequest

router = APIRouter(prefix="/applications", tags=["applications"])

def _reference_number() -> str:
    alphabet = string.ascii_uppercase + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(5))
    return f"TPS-{datetime.now(timezone.utc).year}-{suffix}"


@router.post("", status_code=201)
async def submit_application(
    request: ApplicationSubmitRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    payment = await session.get(PaymentRecord, request.payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment session not found.")
    if payment.status != "verified":
        raise HTTPException(
            status_code=402,
            detail="Application submission is available only after an administrator confirms payment.",
        )

    existing = await session.scalar(
        select(ApplicationRecord).where(ApplicationRecord.payment_id == request.payment_id)
    )
    if existing is not None:
        return _application_receipt(existing)

    draft = payment.application
    application = ApplicationRecord(
        id=request.payment_id,
        reference_no=_reference_number(),
        status="submitted",
        payment_id=request.payment_id,
        payment_utr=payment.utr,
        **draft,
        created_at=datetime.now(timezone.utc),
        confirmed_at=None,
    )
    try:
        session.add(application)
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await session.scalar(
            select(ApplicationRecord).where(ApplicationRecord.payment_id == request.payment_id)
        )
        if existing is None:
            raise
        return _application_receipt(existing)
    return _application_receipt(application)


def _application_receipt(application: ApplicationRecord) -> dict:
    return {
        "reference_no": application.reference_no,
        "status": application.status,
        "payment_id": application.payment_id,
        "created_at": application.created_at,
    }
