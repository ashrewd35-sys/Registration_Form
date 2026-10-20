"""Pydantic v2 response models for the admin payments/applications panel."""

from datetime import datetime

from pydantic import BaseModel, Field

from models.application import Application


class AdminLoginRequest(BaseModel):
    pin: str = Field(min_length=1)


class AdminSession(BaseModel):
    authenticated: bool


class AdminApplicationRow(Application):
    """Application + its payment details joined for the admin table."""

    payment_status: str | None = None
    amount: float | None = None
    payment_verified_at: datetime | None = None


class AdminPaymentRow(BaseModel):
    """Every UPI payment session, incl. pending/failed ones, with applicant summary."""

    id: str
    amount: float
    currency: str
    status: str
    upi_vpa: str
    utr: str | None = None
    applicant_name: str | None = None
    applicant_phone: str | None = None
    application_ref: str | None = None
    created_at: datetime
    verified_at: datetime | None = None
