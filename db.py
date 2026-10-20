"""PostgreSQL connection, application tables, and request-scoped sessions."""

import os
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

database_url = os.getenv("DATABASE_URL", "").strip()
if not database_url:
    raise RuntimeError("DATABASE_URL must be configured before starting the API.")

if database_url.startswith("postgres://"):
    database_url = "postgresql+psycopg://" + database_url.removeprefix("postgres://")
elif database_url.startswith("postgresql://"):
    database_url = "postgresql+psycopg://" + database_url.removeprefix("postgresql://")

engine = create_async_engine(database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
JSON_DOCUMENT = JSON().with_variant(JSONB, "postgresql")


class Base(DeclarativeBase):
    pass


class PaymentRecord(Base):
    __tablename__ = "payments"
    __table_args__ = (
        Index("ix_payments_created_at", "created_at"),
        UniqueConstraint("utr", name="uq_payments_utr"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    upi_vpa: Mapped[str] = mapped_column(String(255), nullable=False)
    payee_name: Mapped[str] = mapped_column(String(255), nullable=False)
    upi_note: Mapped[str] = mapped_column(String(255), nullable=False)
    upi_link: Mapped[str] = mapped_column(Text, nullable=False)
    application: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
    utr: Mapped[str | None] = mapped_column(String(12))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    utr_submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApplicationRecord(Base):
    __tablename__ = "applications"
    __table_args__ = (Index("ix_applications_created_at", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    reference_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    payment_id: Mapped[str] = mapped_column(
        ForeignKey("payments.id", ondelete="RESTRICT"),
        unique=True,
        nullable=False,
    )
    payment_utr: Mapped[str | None] = mapped_column(String(12))
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str] = mapped_column(String(10), nullable=False)
    whatsapp: Mapped[str] = mapped_column(String(10), nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    district: Mapped[str] = mapped_column(String(160), nullable=False)
    professions: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, nullable=False)
    has_shop: Mapped[str] = mapped_column(String(120), nullable=False)
    experience: Mapped[str] = mapped_column(String(32), nullable=False)
    comments: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    await engine.dispose()
