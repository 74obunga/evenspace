"""Registration reservation, payment reconciliation, and ticket issuance."""
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import secrets
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.events.models import (
    Event, EventStatus, EventVisibility, Registration, RegistrationStatus,
    Ticket, TicketStatus, TicketType,
)
from app.modules.events.service import (
    CapacityReached, EventConflict, EventNotFound, TicketTypeNotFound,
    _credential_hash, _utc,
)
from app.modules.payments.models import (
    Payment, PaymentStatus, PaymentWebhook, WebhookStatus,
)
from app.modules.notifications.service import enqueue_notification, enqueue_ticket_issuance, schedule_event_reminder


class CheckoutUnavailable(Exception):
    pass


class PaymentNotFound(Exception):
    pass


def _ticket_credential(idempotency_key: str, ticket_id: UUID) -> str:
    key_hash = hashlib.sha256(idempotency_key.encode()).hexdigest()
    return _ticket_credential_from_hash(key_hash, ticket_id)


def _ticket_credential_from_hash(key_hash: str, ticket_id: UUID) -> str:
    raw = f"evenspace:ticket:v1:{ticket_id}:{key_hash}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def reserve_paid_registration(
    db: Session, *, event_id: UUID, ticket_type_id: UUID, full_name: str,
    email: str, idempotency_key: str,
) -> tuple[Registration, Payment, bool]:
    event = db.scalar(select(Event).where(Event.id == event_id).with_for_update())
    if event is None or event.status != EventStatus.PUBLISHED or event.visibility != EventVisibility.PUBLIC:
        raise EventNotFound
    ticket_type = db.scalar(select(TicketType).where(
        TicketType.id == ticket_type_id, TicketType.event_id == event.id,
        TicketType.is_active.is_(True),
    ).with_for_update())
    if ticket_type is None:
        raise TicketTypeNotFound
    if ticket_type.price <= 0:
        raise EventConflict("Select a paid ticket type for M-Pesa checkout")
    if ticket_type.price != ticket_type.price.to_integral_value():
        raise EventConflict("M-Pesa ticket prices must be in whole Kenyan shillings")

    normalized_email = email.strip().casefold()
    key_hash = hashlib.sha256(idempotency_key.encode()).hexdigest()
    existing = db.scalar(select(Registration).where(
        Registration.event_id == event.id, Registration.email == normalized_email,
    ))
    if existing is not None:
        if existing.idempotency_key_hash != key_hash:
            raise EventConflict("This email is already registered for the event")
        payment = db.scalar(select(Payment).where(Payment.registration_id == existing.id)
                            .order_by(Payment.attempt.desc()))
        if payment is None:
            raise EventConflict("Existing registration has no payment attempt")
        return existing, payment, False
    key_owner = db.scalar(select(Registration).where(
        Registration.event_id == event.id, Registration.idempotency_key_hash == key_hash,
    ))
    if key_owner is not None:
        raise EventConflict("This idempotency key was already used for another registration")

    now = datetime.now(timezone.utc)
    if event.registration_open_at and now < _utc(event.registration_open_at):
        raise EventConflict("Registration has not opened")
    if (event.registration_close_at and now >= _utc(event.registration_close_at)) or now >= _utc(event.start_at):
        raise EventConflict("Registration is closed")

    event_reservation = db.execute(update(Event).where(
        Event.id == event.id, Event.status == EventStatus.PUBLISHED,
        or_(Event.capacity.is_(None), Event.registration_count < Event.capacity),
    ).values(registration_count=Event.registration_count + 1))
    if event_reservation.rowcount != 1:
        raise CapacityReached("This event is full")
    ticket_reservation = db.execute(update(TicketType).where(
        TicketType.id == ticket_type.id, TicketType.is_active.is_(True),
        or_(TicketType.capacity.is_(None), TicketType.registration_count < TicketType.capacity),
    ).values(registration_count=TicketType.registration_count + 1))
    if ticket_reservation.rowcount != 1:
        raise CapacityReached("This ticket type is full")

    registration = Registration(
        event_id=event.id, ticket_type_id=ticket_type.id, full_name=full_name.strip(),
        email=normalized_email, idempotency_key_hash=key_hash,
        status=RegistrationStatus.PENDING_PAYMENT,
        confirmation_code=secrets.token_urlsafe(18),
    )
    db.add(registration)
    db.flush()
    payment = Payment(
        event_id=event.id, registration_id=registration.id, provider="daraja", attempt=1,
        amount=ticket_type.price, currency="KES", status=PaymentStatus.PENDING,
    )
    db.add(payment)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise EventConflict("This email or idempotency key is already registered") from None
    db.refresh(registration)
    db.refresh(payment)
    return registration, payment, True


def store_checkout_result(
    db: Session, payment_id: UUID, result: dict,
) -> Payment:
    payment = db.scalar(select(Payment).where(Payment.id == payment_id).with_for_update())
    if payment is None:
        raise PaymentNotFound
    checkout_id = result.get("CheckoutRequestID")
    merchant_id = result.get("MerchantRequestID")
    if not isinstance(checkout_id, str) or not checkout_id or not isinstance(merchant_id, str) or not merchant_id:
        raise EventConflict("Daraja did not return valid checkout identifiers")
    payment.provider_checkout_id = checkout_id[:120]
    payment.provider_merchant_request_id = merchant_id[:120]
    db.commit()
    db.refresh(payment)
    return payment


def link_early_webhook(db: Session, payment: Payment) -> bool:
    """Associate a callback that raced the STK response persistence."""
    if not payment.provider_checkout_id:
        return False
    inbox = db.scalar(select(PaymentWebhook).where(
        PaymentWebhook.provider == "daraja",
        PaymentWebhook.provider_event_id == payment.provider_checkout_id,
        PaymentWebhook.payment_id.is_(None),
    ).with_for_update())
    if inbox is None:
        return False
    inbox.payment_id = payment.id
    inbox.status = WebhookStatus.RECEIVED
    inbox.rejection_reason = None
    db.commit()
    return True


def _metadata_items(payload: dict) -> dict[str, object]:
    callback = payload.get("Body", {}).get("stkCallback", {})
    items = callback.get("CallbackMetadata", {}).get("Item", [])
    if not isinstance(items, list):
        return {}
    return {
        item.get("Name"): item.get("Value")
        for item in items
        if isinstance(item, dict) and isinstance(item.get("Name"), str) and "Value" in item
    }


def begin_webhook(db: Session, payload: dict) -> tuple[PaymentWebhook | None, Payment | None, bool]:
    callback = payload.get("Body", {}).get("stkCallback", {})
    checkout_id = callback.get("CheckoutRequestID")
    if not isinstance(checkout_id, str) or not checkout_id or len(checkout_id) > 120:
        raise ValueError("Malformed Daraja callback")
    payment = db.scalar(select(Payment).where(
        Payment.provider == "daraja", Payment.provider_checkout_id == checkout_id,
    ).with_for_update())
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    inbox = PaymentWebhook(
        provider="daraja", provider_event_id=checkout_id[:160],
        payment_id=payment.id if payment else None, payload_digest=digest,
        status=WebhookStatus.RECEIVED if payment else WebhookStatus.REJECTED,
        rejection_reason=None if payment else "unknown_checkout_id",
    )
    db.add(inbox)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return None, None, True
    db.commit()
    if payment:
        db.refresh(payment)
    return inbox, payment, False


def reconcile_payment(db: Session, payment_id: UUID, query_result: dict, callback_payload: dict | None = None) -> Payment:
    payment = db.scalar(select(Payment).where(Payment.id == payment_id).with_for_update())
    if payment is None:
        raise PaymentNotFound
    if payment.status != PaymentStatus.PENDING:
        return payment
    # A transport/provider rejection is not a transaction result; keep it pending for retry.
    if str(query_result.get("ResponseCode", "0")) != "0":
        return payment
    result_code = query_result.get("ResultCode")
    if result_code is None:
        return payment
    try:
        succeeded = int(result_code) == 0
    except (TypeError, ValueError):
        return payment

    registration = db.scalar(select(Registration).where(
        Registration.id == payment.registration_id,
    ).with_for_update())
    if registration is None:
        return payment
    if succeeded:
        metadata = _metadata_items(callback_payload or {})
        if "Amount" in metadata:
            try:
                callback_amount = Decimal(str(metadata["Amount"]))
            except Exception:
                return payment
            if callback_amount != payment.amount:
                return payment
        receipt = metadata.get("MpesaReceiptNumber")
        if receipt is not None and (not isinstance(receipt, str) or not receipt.strip()):
            return payment
        ticket_id = registration.id
        credential = _ticket_credential_from_hash(registration.idempotency_key_hash, ticket_id)
        db.add(Ticket(
            id=ticket_id, event_id=registration.event_id, registration_id=registration.id,
            ticket_type_id=registration.ticket_type_id,
            credential_hash=_credential_hash(credential), status=TicketStatus.ACTIVE,
        ))
        payment.provider_receipt_id = receipt[:40] if isinstance(receipt, str) else None
        payment.status = PaymentStatus.SUCCEEDED
        payment.succeeded_at = datetime.now(timezone.utc)
        registration.status = RegistrationStatus.CONFIRMED
        event = db.get(Event, registration.event_id)
        enqueue_notification(
            db, workspace_id=event.workspace_id, kind="payment_confirmation",
            recipient_email=registration.email, template_key="payment_confirmation",
            context={"full_name": registration.full_name, "event_title": event.title,
                     "event_start": event.start_at.isoformat()},
            dedupe_key=f"payment:{payment.id}:confirmation",
        )
        enqueue_ticket_issuance(
            db, workspace_id=event.workspace_id, recipient_email=registration.email,
            full_name=registration.full_name, event_title=event.title,
            event_start=event.start_at.isoformat(), credential=credential,
            dedupe_key=f"registration:{registration.id}:ticket",
        )
        schedule_event_reminder(db, workspace_id=event.workspace_id, event=event, registration=registration)
    else:
        payment.status = PaymentStatus.FAILED
        payment.failure_code = str(result_code)[:80]
        payment.failure_reason = str(query_result.get("ResultDesc", "Payment failed"))[:500]
        if registration.status == RegistrationStatus.PENDING_PAYMENT:
            db.execute(update(Event).where(Event.id == registration.event_id,
                                           Event.registration_count > 0)
                       .values(registration_count=Event.registration_count - 1))
            db.execute(update(TicketType).where(TicketType.id == registration.ticket_type_id,
                                                 TicketType.registration_count > 0)
                       .values(registration_count=TicketType.registration_count - 1))
            registration.status = RegistrationStatus.CANCELLED
    db.commit()
    db.refresh(payment)
    return payment


def payment_public_status(db: Session, payment_id: UUID, idempotency_key: str) -> tuple[Payment, str | None]:
    payment = db.scalar(select(Payment).where(Payment.id == payment_id))
    if payment is None:
        raise PaymentNotFound
    registration = db.get(Registration, payment.registration_id)
    if registration is None or not secrets.compare_digest(
        registration.idempotency_key_hash, hashlib.sha256(idempotency_key.encode()).hexdigest(),
    ):
        raise PaymentNotFound
    credential = None
    if payment.status == PaymentStatus.SUCCEEDED:
        ticket = db.scalar(select(Ticket).where(Ticket.registration_id == registration.id))
        if ticket and ticket.status == TicketStatus.ACTIVE:
            credential = _ticket_credential(idempotency_key, ticket.id)
            if _credential_hash(credential) != ticket.credential_hash:
                credential = None
    return payment, credential
