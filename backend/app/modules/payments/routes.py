from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.modules.events.schemas import PaidRegistrationRequest, PaidRegistrationResponse
from app.modules.events.models import Event, Registration, TicketType
from app.modules.events.service import CapacityReached, EventConflict, EventNotFound, TicketTypeNotFound
from app.modules.identity.dependencies import AuthContext, require_csrf, require_workspace_manager
from app.modules.payments.models import Payment, PaymentStatus, WebhookStatus
from app.modules.payments.providers.daraja import DarajaClient, DarajaError, DarajaUnavailable
from app.modules.payments.service import (
    PaymentNotFound,
    begin_webhook,
    link_early_webhook,
    payment_public_status,
    reconcile_payment,
    reserve_paid_registration,
    store_checkout_result,
)
from app.modules.payments.refunds import RefundConflict, RefundNotFound, list_refunds, request_refund


router = APIRouter(prefix="/payments", tags=["payments"])
refund_router = APIRouter(prefix="/workspaces/{workspace_id}/payments", tags=["refunds"])


class RefundRequestBody(BaseModel):
    amount: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("reason")
    @classmethod
    def _reason_is_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 3:
            raise ValueError("Refund reason must contain at least three characters")
        return cleaned


class RefundResponse(BaseModel):
    id: UUID
    payment_id: UUID
    amount: Decimal
    currency: str
    status: str
    reason: str
    message: str


class PaymentStatusResponse(BaseModel):
    registration_id: UUID
    payment_id: UUID
    status: str
    amount: Decimal
    currency: str
    ticket_credential: str | None = None


def _response(registration: Registration, payment: Payment, credential: str | None = None):
    if payment.status == PaymentStatus.PENDING:
        if payment.provider_checkout_id:
            message = "A payment prompt has been sent to your M-Pesa phone. Complete it to receive your ticket."
        else:
            message = "We are checking the payment request. Do not submit another payment request."
    elif payment.status == PaymentStatus.SUCCEEDED:
        message = "Payment confirmed. Your ticket is ready."
    else:
        message = "Payment was not completed. Contact the event organizer for help."
    return PaidRegistrationResponse(
        registration_id=registration.id,
        payment_id=payment.id,
        status=payment.status.value,
        amount=payment.amount,
        currency=payment.currency,
        message=message,
        ticket_credential=credential,
    )


@router.post("/public/events/{event_id}/registrations", response_model=PaidRegistrationResponse,
            status_code=202)
async def start_paid_registration(
    event_id: UUID,
    payload: PaidRegistrationRequest,
    response: Response,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    if not settings.daraja_ready:
        raise HTTPException(status_code=503, detail="M-Pesa checkout is not configured")
    try:
        registration, payment, created = reserve_paid_registration(
            db,
            event_id=event_id,
            ticket_type_id=payload.ticket_type_id,
            full_name=payload.full_name,
            email=str(payload.email),
            idempotency_key=str(idempotency_key),
        )
    except EventNotFound:
        raise HTTPException(status_code=404, detail="Event not found") from None
    except TicketTypeNotFound:
        raise HTTPException(status_code=404, detail="Ticket type not found for this event") from None
    except CapacityReached as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except EventConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None

    credential = None
    if payment.status == PaymentStatus.SUCCEEDED:
        try:
            _, credential = payment_public_status(db, payment.id, str(idempotency_key))
        except PaymentNotFound:
            credential = None
        response.status_code = 200
        return _response(registration, payment, credential)
    if not created:
        # Never send a second STK prompt on an idempotent retry. The browser polls payment status.
        response.status_code = 200
        return _response(registration, payment)

    event = db.get(Event, event_id)
    ticket_type = db.get(TicketType, registration.ticket_type_id)
    try:
        async with DarajaClient(settings) as daraja:
            result = await daraja.initiate_stk_push(
                phone_number=payload.phone_number,
                amount=payment.amount,
                account_reference=registration.confirmation_code,
                description=f"{event.title} {ticket_type.name}",
            )
        payment = store_checkout_result(db, payment.id, result)
        if link_early_webhook(db, payment):
            payment = await _reconcile(db, payment)
    except (DarajaError, DarajaUnavailable, EventConflict) as exc:
        # A timeout can mean Daraja accepted the request. Keep the reservation pending and
        # never retry the prompt automatically; reconciliation can safely resolve it later.
        response.status_code = 202
        return PaidRegistrationResponse(
            registration_id=registration.id, payment_id=payment.id, status="pending",
            amount=payment.amount, currency=payment.currency,
            message="Payment initiation is being checked. Do not submit another payment request.",
        )
    return _response(registration, payment)


async def _reconcile(db: Session, payment: Payment, callback_payload: dict | None = None) -> Payment:
    if payment.status != PaymentStatus.PENDING or not payment.provider_checkout_id:
        return payment
    settings = get_settings()
    try:
        async with DarajaClient(settings) as daraja:
            result = await daraja.query_stk_push(checkout_request_id=payment.provider_checkout_id)
    except (DarajaError, DarajaUnavailable):
        return payment
    return reconcile_payment(db, payment.id, result, callback_payload)


@router.get("/{payment_id}", response_model=PaymentStatusResponse)
async def get_payment_status(
    payment_id: UUID,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    try:
        payment, _ = payment_public_status(db, payment_id, str(idempotency_key))
    except PaymentNotFound:
        raise HTTPException(status_code=404, detail="Payment not found") from None
    payment = await _reconcile(db, payment)
    try:
        payment, credential = payment_public_status(db, payment_id, str(idempotency_key))
    except PaymentNotFound:
        raise HTTPException(status_code=404, detail="Payment not found") from None
    registration = db.get(Registration, payment.registration_id)
    return PaymentStatusResponse(
        registration_id=registration.id,
        payment_id=payment.id,
        status=payment.status.value,
        amount=payment.amount,
        currency=payment.currency,
        ticket_credential=credential,
    )


@router.post("/daraja/callback")
async def daraja_callback(payload: dict, db: Session = Depends(get_db)):
    try:
        inbox, payment, duplicate = begin_webhook(db, payload)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Malformed Daraja callback") from None
    if duplicate:
        return {"ResultCode": 0, "ResultDesc": "Callback already received"}
    if payment is not None:
        await _reconcile(db, payment, payload)
        if inbox is not None:
            inbox.status = WebhookStatus.PROCESSED
            db.commit()
    return {"ResultCode": 0, "ResultDesc": "Callback received"}


@refund_router.post("/{payment_id}/refunds", response_model=RefundResponse, status_code=202)
def create_refund_request(
    workspace_id: UUID,
    payment_id: UUID,
    payload: RefundRequestBody,
    response: Response,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    context: AuthContext = Depends(require_workspace_manager),
    _csrf: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    try:
        refund, created = request_refund(
            db, workspace_id=workspace_id, payment_id=payment_id,
            requested_by_id=context.user.id, idempotency_key=str(idempotency_key),
            amount=payload.amount, reason=payload.reason,
        )
    except RefundNotFound:
        raise HTTPException(status_code=404, detail="Payment not found") from None
    except RefundConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    if not created:
        response.status_code = 200
    return RefundResponse(
        id=refund.id, payment_id=refund.payment_id, amount=refund.amount,
        currency=refund.currency, status=refund.status.value, reason=refund.reason,
        message="Refund request recorded. No M-Pesa reversal has been sent.",
    )


@refund_router.get("/{payment_id}/refunds", response_model=list[RefundResponse])
def get_refund_requests(
    workspace_id: UUID,
    payment_id: UUID,
    _manager: AuthContext = Depends(require_workspace_manager),
    db: Session = Depends(get_db),
):
    try:
        refunds = list_refunds(db, workspace_id=workspace_id, payment_id=payment_id)
    except RefundNotFound:
        raise HTTPException(status_code=404, detail="Payment not found") from None
    return [RefundResponse(
        id=refund.id, payment_id=refund.payment_id, amount=refund.amount,
        currency=refund.currency, status=refund.status.value, reason=refund.reason,
        message="Refund request recorded. No M-Pesa reversal has been sent.",
    ) for refund in refunds]
