from datetime import datetime
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, EmailStr, Field, UUID4, field_validator, model_validator
from typing import Literal


class EventCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10000)
    category: str = Field(default="event", min_length=1, max_length=80)
    visibility: Literal["public", "private"] = "private"
    start_at: datetime
    end_at: datetime
    timezone: str = Field(min_length=1, max_length=80)
    registration_open_at: datetime | None = None
    registration_close_at: datetime | None = None
    capacity: int | None = Field(default=None, ge=1)

    @field_validator("title", "category")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Value cannot be blank")
        return value.strip()

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Use a valid IANA timezone, such as Africa/Nairobi") from exc
        return value

    @model_validator(mode="after")
    def valid_schedule(self):
        datetimes = [self.start_at, self.end_at]
        if self.registration_open_at is not None:
            datetimes.append(self.registration_open_at)
        if self.registration_close_at is not None:
            datetimes.append(self.registration_close_at)
        if any(value.tzinfo is None or value.utcoffset() is None for value in datetimes):
            raise ValueError("Event times must include a UTC offset")
        if self.end_at <= self.start_at:
            raise ValueError("Event end must be after its start")
        if self.registration_open_at and self.registration_close_at:
            if self.registration_close_at <= self.registration_open_at:
                raise ValueError("Registration close must be after registration opens")
        if self.registration_close_at and self.registration_close_at > self.start_at:
            raise ValueError("Registration must close by the event start")
        if self.registration_open_at and self.registration_open_at >= self.start_at:
            raise ValueError("Registration must open before the event starts")
        return self


class EventUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10000)
    category: str | None = Field(default=None, min_length=1, max_length=80)
    start_at: datetime | None = None
    end_at: datetime | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=80)

    @field_validator("title", "category")
    @classmethod
    def non_blank_update(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not value.strip():
            raise ValueError("Value cannot be blank")
        return value.strip()

    @field_validator("timezone")
    @classmethod
    def known_update_timezone(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                ZoneInfo(value)
            except ZoneInfoNotFoundError as exc:
                raise ValueError("Use a valid IANA timezone") from exc
        return value

    @model_validator(mode="after")
    def non_empty_update(self):
        if not self.model_fields_set:
            raise ValueError("Provide at least one event field to update")
        for value in (self.start_at, self.end_at):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError("Event times must include a UTC offset")
        return self


class EventCancelRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("reason")
    @classmethod
    def non_blank_reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("Cancellation reason must contain at least three characters")
        return value


class EventResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    title: str
    description: str | None
    category: str
    status: str
    visibility: str
    start_at: datetime
    end_at: datetime
    timezone: str
    registration_open_at: datetime | None
    registration_close_at: datetime | None
    capacity: int | None
    registration_count: int


class TicketTypeCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=4000)
    price: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=12, decimal_places=2)
    capacity: int | None = Field(default=None, ge=1)

    @field_validator("name")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Ticket type name cannot be blank")
        return value.strip()

    @field_validator("price")
    @classmethod
    def whole_kes_amount(cls, value: Decimal) -> Decimal:
        if value != value.to_integral_value():
            raise ValueError("M-Pesa ticket prices must be in whole Kenyan shillings")
        return value


class TicketTypeResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    price: Decimal
    capacity: int | None
    registration_count: int


class OrganizerEventResponse(EventResponse):
    ticket_types: list[TicketTypeResponse]


class PublicTicketTypeResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    price: Decimal
    capacity: int | None


class PublicEventResponse(BaseModel):
    id: UUID
    title: str
    description: str | None
    category: str
    start_at: datetime
    end_at: datetime
    timezone: str
    capacity: int | None
    registration_close_at: datetime | None
    ticket_types: list[PublicTicketTypeResponse]


class PublicRegistrationRequest(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    ticket_type_id: UUID

    @field_validator("full_name")
    @classmethod
    def non_blank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Name cannot be blank")
        return value.strip()


class PaidRegistrationRequest(PublicRegistrationRequest):
    phone_number: str = Field(min_length=10, max_length=16)

    @field_validator("phone_number")
    @classmethod
    def normalize_kenyan_phone(cls, value: str) -> str:
        phone = value.strip().replace("+", "")
        if phone.startswith("0"):
            phone = "254" + phone[1:]
        if not phone.isdigit() or not phone.startswith("254") or len(phone) != 12:
            raise ValueError("Use a Kenyan mobile number in 07XXXXXXXX or 2547XXXXXXXX format")
        return phone


class PaidRegistrationResponse(BaseModel):
    registration_id: UUID
    payment_id: UUID
    status: str
    amount: Decimal
    currency: str
    message: str
    ticket_credential: str | None = None


class RegistrationResponse(BaseModel):
    id: UUID
    event_id: UUID
    ticket_type_id: UUID
    ticket_id: UUID
    ticket_credential: str
    full_name: str
    email: EmailStr
    status: str
    confirmation_code: str
    registered_at: datetime


class TicketLookupRequest(BaseModel):
    credential: str = Field(pattern=r"^[0-9a-f]{64}$")


class ParticipantTicketResponse(BaseModel):
    ticket_id: UUID
    event_id: UUID
    event_title: str
    start_at: datetime
    end_at: datetime
    timezone: str
    ticket_type_name: str
    attendee_name: str
    status: str


class AttendanceCheckInRequest(BaseModel):
    ticket_credential: str = Field(pattern=r"^[0-9a-f]{64}$")
    scan_event_id: UUID4


class AttendanceCheckInResponse(BaseModel):
    attendance_event_id: UUID
    event_id: UUID
    ticket_id: UUID
    attendee_name: str
    event_type: str
    scanned_at: datetime
    duplicate: bool


class AttendanceRecordResponse(BaseModel):
    attendance_event_id: UUID
    ticket_id: UUID
    attendee_name: str
    scanned_at: datetime


class OrganizerRegistrationResponse(BaseModel):
    id: UUID
    full_name: str
    email: EmailStr
    status: str
    ticket_type: str
    ticket_status: str | None
    registered_at: datetime
    checked_in_at: datetime | None


class OperatorAssignmentResponse(BaseModel):
    event_id: UUID
    user_id: UUID
    assigned_at: datetime


class TicketRevokeResponse(BaseModel):
    id: UUID
    status: str
    revoked_at: datetime | None


class ScanDeviceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    expires_in_days: int = Field(default=14, ge=1, le=30)

    @field_validator("name")
    @classmethod
    def non_blank_device(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Device name cannot be blank")
        return value.strip()


class ScanDeviceResponse(BaseModel):
    id: UUID
    event_id: UUID
    name: str
    token: str
    expires_at: datetime


class ScanDeviceItemResponse(BaseModel):
    id: UUID
    event_id: UUID
    name: str
    expires_at: datetime
    revoked_at: datetime | None = None
    created_at: datetime
    is_active: bool


class OfflineManifestTicket(BaseModel):
    ticket_id: UUID
    credential_hash: str
    status: str
    attendee_name: str


class OfflineManifestResponse(BaseModel):
    snapshot_id: UUID
    generated_at: datetime
    event_id: UUID
    event_title: str
    starts_at: datetime
    tickets: list[OfflineManifestTicket]


class OfflineScanItem(BaseModel):
    scan_event_id: UUID4
    credential: str = Field(pattern=r"^[0-9a-f]{64}$")
    scanned_at: datetime

    @field_validator("scanned_at")
    @classmethod
    def aware_scan_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Scan time must include a UTC offset")
        return value


class OfflineSyncRequest(BaseModel):
    batch_id: UUID4
    snapshot_id: UUID
    scans: list[OfflineScanItem] = Field(max_length=500)


class OfflineConflictResponse(BaseModel):
    id: UUID
    scan_event_id: UUID
    ticket_id: UUID | None
    attendee_name: str | None
    scanned_at: datetime
    reason: str
    status: str
    resolution_note: str | None


class OfflineConflictResolveRequest(BaseModel):
    action: Literal["accept", "ignore"]
    note: str | None = Field(default=None, max_length=500)

