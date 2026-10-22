import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    PARTIALLY_REFUNDED = "partially_refunded"
    REFUNDED = "refunded"


class RefundStatus(str, enum.Enum):
    REQUESTED = "requested"
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class WebhookStatus(str, enum.Enum):
    RECEIVED = "received"
    PROCESSED = "processed"
    REJECTED = "rejected"


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("provider", "provider_checkout_id", name="uq_payment_provider_checkout"),
        UniqueConstraint("provider_receipt_id", name="uq_payment_provider_receipt"),
        UniqueConstraint("registration_id", "attempt", name="uq_payment_registration_attempt"),
        CheckConstraint("amount > 0", name="ck_payment_amount_positive"),
        CheckConstraint("attempt > 0", name="ck_payment_attempt_positive"),
        CheckConstraint("length(currency) = 3", name="ck_payment_currency_length"),
        Index("ix_payments_status_created", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="RESTRICT"), index=True)
    registration_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("registrations.id", ondelete="RESTRICT"), index=True
    )
    provider: Mapped[str] = mapped_column(String(32))
    attempt: Mapped[int] = mapped_column(default=1)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="KES", server_default="KES")
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, name="payment_status"), default=PaymentStatus.PENDING
    )
    provider_checkout_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    provider_merchant_request_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    provider_receipt_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    succeeded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Refund(Base):
    __tablename__ = "refunds"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_refund_amount_positive"),
        CheckConstraint("length(currency) = 3", name="ck_refund_currency_length"),
        UniqueConstraint("provider", "provider_refund_id", name="uq_refund_provider_reference"),
        UniqueConstraint("payment_id", "idempotency_key_hash", name="uq_refund_payment_idempotency"),
        Index("ix_refunds_payment_status", "payment_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    payment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payments.id", ondelete="RESTRICT"), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="KES", server_default="KES")
    status: Mapped[RefundStatus] = mapped_column(
        Enum(RefundStatus, name="refund_status"), default=RefundStatus.REQUESTED
    )
    reason: Mapped[str] = mapped_column(String(500))
    idempotency_key_hash: Mapped[str] = mapped_column(String(64))
    request_digest: Mapped[str] = mapped_column(String(64))
    requested_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    provider_refund_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PaymentWebhook(Base):
    """Idempotency inbox. Store payload digests and normalized IDs, never raw callback PII."""

    __tablename__ = "payment_webhooks"
    __table_args__ = (
        UniqueConstraint("provider", "provider_event_id", name="uq_payment_webhook_provider_event"),
        Index("ix_payment_webhooks_status_received", "status", "received_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(32))
    provider_event_id: Mapped[str] = mapped_column(String(160))
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("payments.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    payload_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[WebhookStatus] = mapped_column(
        Enum(WebhookStatus, name="payment_webhook_status"), default=WebhookStatus.RECEIVED
    )
    rejection_reason: Mapped[str | None] = mapped_column(String(160), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
