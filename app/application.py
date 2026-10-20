"""Pydantic v2 models for the Channel Partner application and its payment gate."""

import uuid
from datetime import datetime, timezone
from typing import List

from pydantic import BaseModel, EmailStr, Field


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class ApplicationDraft(BaseModel):
    """Registration-form fields — collected client-side, stored on the payment
    session, and promoted to an Application only after the fee payment is verified."""

    full_name: str = Field(min_length=1)
    phone: str = Field(pattern=r"^\d{10}$")
    whatsapp: str = Field(pattern=r"^\d{10}$")
    email: EmailStr
    district: str = Field(min_length=1)
    professions: List[str] = Field(min_length=1)
    has_shop: str = Field(min_length=1)
    experience: str = Field(min_length=1)
    comments: str = ""


class ApplicationSubmitRequest(BaseModel):
    payment_id: str


class Application(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    reference_no: str
    status: str = "submitted"
    payment_id: str
    payment_utr: str | None = None
    full_name: str
    phone: str
    whatsapp: str
    email: str
    district: str
    professions: List[str]
    has_shop: str
    experience: str
    comments: str = ""
    created_at: datetime = Field(default_factory=_now_utc)
    confirmed_at: datetime | None = None  # set by the admin panel's confirm action
