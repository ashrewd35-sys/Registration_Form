"""Pydantic v2 models for UPI payment sessions (the application-fee gate)."""

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class UtrSubmitRequest(BaseModel):
    utr: str = Field(pattern=r"^\d{12}$")


class PaymentSession(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    amount: float
    currency: str = "INR"
    status: str = "pending"  # pending | pending_review | verified | failed
    upi_vpa: str
    payee_name: str
    upi_note: str
    upi_link: str
    utr: str | None = None
    created_at: datetime = Field(default_factory=_now_utc)
    verified_at: datetime | None = None
