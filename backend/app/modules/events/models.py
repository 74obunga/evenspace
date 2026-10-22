import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class EventStatus(str, enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    IN_PROGRESS = "in_progress"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class EventVisibility(str, enum.Enum):
    PUBLIC = "public"
    PRIVATE = "private"


class RegistrationStatus(str, enum.Enum):
    CONFIRMED = "confirmed"
    PENDING_PAYMENT = "pending_payment"
    CANCELLED = "cancelled"


class TicketStatus(str, enum.Enum):
    ACTIVE = "active"
    REVOKED = "revoked"


class AttendanceEventType(str, enum.Enum):
    CHECK_IN = "check_in"


class OfflineConflictStatus(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    IGNORED = "ignored"


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint("capacity IS NULL OR capacity > 0", name="ck_event_capacity_positive"),
        CheckConstraint("registration_count >= 0", name="ck_event_registration_count_nonnegative"),
        CheckConstraint("end_at > start_at", name="ck_event_end_after_start"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="RESTRICT"), index=True)
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(80), default="event")
    status: Mapped[EventStatus] = mapped_column(Enum(EventStatus, name="event_status"), default=EventStatus.DRAFT)
    visibility: Mapped[EventVisibility] = mapped_column(
        Enum(EventVisibility, name="event_visibility"), default=EventVisibility.PRIVATE
    )
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(String(80))
    registration_open_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    registration_close_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    registration_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ticket_types: Mapped[list["TicketType"]] = relationship(back_populates="event")


class TicketType(Base):
    __tablename__ = "ticket_types"
    __table_args__ = (
        UniqueConstraint("event_id", "name", name="uq_ticket_type_event_name"),
        CheckConstraint("price >= 0", name="ck_ticket_type_price_nonnegative"),
        CheckConstraint("capacity IS NULL OR capacity > 0", name="ck_ticket_type_capacity_positive"),
        CheckConstraint("registration_count >= 0", name="ck_ticket_type_registration_count_nonnegative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"), server_default="0")
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    registration_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")

    event: Mapped[Event] = relationship(back_populates="ticket_types")


class Registration(Base):
    __tablename__ = "registrations"
    __table_args__ = (
        UniqueConstraint("event_id", "email", name="uq_registration_event_email"),
        UniqueConstraint("event_id", "idempotency_key_hash", name="uq_registration_event_idempotency_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="RESTRICT"), index=True)
    ticket_type_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ticket_types.id", ondelete="RESTRICT"), index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320))
    idempotency_key_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[RegistrationStatus] = mapped_column(
        Enum(RegistrationStatus, name="registration_status"), default=RegistrationStatus.CONFIRMED
    )
    confirmation_code: Mapped[str] = mapped_column(String(48), unique=True, index=True)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="RESTRICT"), index=True)
    registration_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("registrations.id", ondelete="RESTRICT"), unique=True, index=True
    )
    ticket_type_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ticket_types.id", ondelete="RESTRICT"), index=True)
    credential_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[TicketStatus] = mapped_column(Enum(TicketStatus, name="ticket_status"), default=TicketStatus.ACTIVE)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EventOperatorAssignment(Base):
    __tablename__ = "event_operator_assignments"
    __table_args__ = (UniqueConstraint("event_id", "user_id", name="uq_event_operator_user"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="RESTRICT"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    assigned_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AttendanceEvent(Base):
    __tablename__ = "attendance_events"
    __table_args__ = (
        UniqueConstraint("event_id", "ticket_id", "event_type", name="uq_attendance_event_ticket_type"),
        UniqueConstraint("scan_event_id", name="uq_attendance_scan_event_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="RESTRICT"), index=True)
    ticket_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tickets.id", ondelete="RESTRICT"), index=True)
    event_type: Mapped[AttendanceEventType] = mapped_column(
        Enum(AttendanceEventType, name="attendance_event_type"), default=AttendanceEventType.CHECK_IN
    )
    scan_event_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    recorded_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    source: Mapped[str] = mapped_column(String(16), default="online", server_default="online")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScanDevice(Base):
    __tablename__ = "scan_devices"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScanDeviceSnapshot(Base):
    __tablename__ = "scan_device_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scan_devices.id", ondelete="RESTRICT"), index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScanDeviceSnapshotTicket(Base):
    __tablename__ = "scan_device_snapshot_tickets"
    __table_args__ = (UniqueConstraint("snapshot_id", "ticket_id", name="uq_snapshot_ticket"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scan_device_snapshots.id", ondelete="RESTRICT"), index=True)
    ticket_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tickets.id", ondelete="RESTRICT"), index=True)
    credential_hash: Mapped[str] = mapped_column(String(64))
    ticket_status: Mapped[str] = mapped_column(String(16))
    attendee_name: Mapped[str] = mapped_column(String(200))


class SyncBatch(Base):
    __tablename__ = "sync_batches"
    __table_args__ = (UniqueConstraint("device_id", "batch_id", name="uq_sync_batch_device_batch"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scan_devices.id", ondelete="RESTRICT"), index=True)
    batch_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scan_device_snapshots.id", ondelete="RESTRICT"))
    request_digest: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSON)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OfflineScanConflict(Base):
    __tablename__ = "offline_scan_conflicts"
    __table_args__ = (UniqueConstraint("scan_event_id", name="uq_offline_conflict_scan_event_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="RESTRICT"), index=True)
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scan_devices.id", ondelete="RESTRICT"), index=True)
    sync_batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sync_batches.id", ondelete="RESTRICT"), index=True)
    scan_event_id: Mapped[uuid.UUID] = mapped_column(Uuid, unique=True)
    ticket_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tickets.id", ondelete="RESTRICT"), nullable=True)
    credential_hash: Mapped[str] = mapped_column(String(64))
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(String(80))
    status: Mapped[OfflineConflictStatus] = mapped_column(
        Enum(OfflineConflictStatus, name="offline_conflict_status"), default=OfflineConflictStatus.PENDING
    )
    resolution_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
