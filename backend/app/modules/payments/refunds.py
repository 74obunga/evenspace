import hashlib
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.events.models import Event, Registration
from app.modules.payments.models import Payment, PaymentStatus, Refund, RefundStatus
from app.modules.notifications.service import enqueue_notification


class RefundConflict(Exception):
    pass


class RefundNotFound(Exception):
    pass


def request_refund(
    db: Session, *, workspace_id: UUID, payment_id: UUID, requested_by_id: UUID,
    idempotency_key: str, amount: Decimal | None, reason: str,
) -> tuple[Refund, bool]:
    payment = db.scalar(
        select(Payment).join(Event, Event.id == Payment.event_id)
        .where(Payment.id == payment_id, Event.workspace_id == workspace_id)
        .with_for_update()
    )
    if payment is None:
        raise RefundNotFound
    if payment.status not in {PaymentStatus.SUCCEEDED, PaymentStatus.PARTIALLY_REFUNDED}:
        raise RefundConflict("Only confirmed payments can be refunded")

    key_hash = hashlib.sha256(idempotency_key.encode()).hexdigest()
    final_reason = reason.strip()
    previous = db.scalar(select(Refund).where(
        Refund.payment_id == payment.id, Refund.idempotency_key_hash == key_hash,
    ))
    if previous is not None:
        request_amount = previous.amount if amount is None else amount
        digest = hashlib.sha256(f"{request_amount:.2f}\n{final_reason}".encode()).hexdigest()
        if previous.request_digest != digest:
            raise RefundConflict("This idempotency key was already used for another refund request")
        return previous, False

    request_amount = amount
    if request_amount is None:
        reserved = db.scalar(select(func.coalesce(func.sum(Refund.amount), 0)).where(
            Refund.payment_id == payment.id,
            Refund.status.in_([RefundStatus.REQUESTED, RefundStatus.PENDING, RefundStatus.SUCCEEDED]),
        ))
        request_amount = payment.amount - Decimal(str(reserved))
    digest = hashlib.sha256(f"{request_amount:.2f}\n{final_reason}".encode()).hexdigest()

    if request_amount <= 0:
        raise RefundConflict("No refundable balance remains")
    reserved = db.scalar(select(func.coalesce(func.sum(Refund.amount), 0)).where(
        Refund.payment_id == payment.id,
        Refund.status.in_([RefundStatus.REQUESTED, RefundStatus.PENDING, RefundStatus.SUCCEEDED]),
    ))
    if Decimal(str(reserved)) + request_amount > payment.amount:
        raise RefundConflict("Refund amount exceeds the remaining refundable balance")

    refund = Refund(
        payment_id=payment.id, provider=payment.provider, amount=request_amount,
        currency=payment.currency, status=RefundStatus.REQUESTED,
        reason=final_reason, requested_by_id=requested_by_id,
        idempotency_key_hash=key_hash, request_digest=digest,
    )
    db.add(refund)
    registration = db.get(Registration, payment.registration_id)
    event = db.get(Event, payment.event_id)
    enqueue_notification(
        db, workspace_id=workspace_id, kind="refund_update", recipient_email=registration.email,
        template_key="refund_update",
        context={"full_name": registration.full_name, "event_title": event.title,
                 "refund_status": "requested"},
        dedupe_key=f"refund:{refund.id}:requested",
    )
    db.commit()
    db.refresh(refund)
    return refund, True


def list_refunds(db: Session, *, workspace_id: UUID, payment_id: UUID) -> list[Refund]:
    payment_exists = db.scalar(
        select(Payment.id).join(Event, Event.id == Payment.event_id)
        .where(Payment.id == payment_id, Event.workspace_id == workspace_id)
    )
    if payment_exists is None:
        raise RefundNotFound
    return list(db.scalars(
        select(Refund).where(Refund.payment_id == payment_id).order_by(Refund.created_at.desc())
    ))
