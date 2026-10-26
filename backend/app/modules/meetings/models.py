import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, LargeBinary, String, Text,
    UniqueConstraint, Uuid, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Meeting(Base):
    __tablename__ = "meetings"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_meeting_event"),
        UniqueConstraint("join_token_hash", name="uq_meetings_join_token_hash"),
        CheckConstraint("status IN ('draft','scheduled','held','cancelled')", name="ck_meeting_status"),
        CheckConstraint("meeting_mode IN ('physical','online')", name="ck_meeting_mode"),
        CheckConstraint(
            "(meeting_mode = 'physical' AND online_url IS NULL) OR "
            "(meeting_mode = 'online' AND online_url IS NOT NULL)",
            name="ck_online_meeting_url",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="RESTRICT"), index=True)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="RESTRICT"), index=True)
    meeting_type: Mapped[str] = mapped_column(String(80))
    meeting_mode: Mapped[str] = mapped_column(String(16), default="physical", server_default="physical")
    online_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    chairperson_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="draft", server_default="draft")
    cancellation_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    join_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MeetingAgendaItem(Base):
    __tablename__ = "meeting_agenda_items"
    __table_args__ = (
        UniqueConstraint("meeting_id", "position", name="uq_meeting_agenda_position"),
        CheckConstraint("position > 0", name="ck_meeting_agenda_position_positive"),
        CheckConstraint("duration_minutes IS NULL OR duration_minutes > 0", name="ck_meeting_agenda_duration_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    meeting_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("meetings.id", ondelete="RESTRICT"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    presenter_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MeetingInvitee(Base):
    __tablename__ = "meeting_invitees"
    __table_args__ = (
        UniqueConstraint("meeting_id", "user_id", name="uq_meeting_invitee"),
        CheckConstraint("attendance_status IN ('pending','present','absent','excused')", name="ck_meeting_attendance_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    meeting_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("meetings.id", ondelete="RESTRICT"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    invited_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    invited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    attendance_status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    attendance_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    recorded_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MeetingGuestRegistration(Base):
    __tablename__ = "meeting_guest_registrations"
    __table_args__ = (
        UniqueConstraint("meeting_id", "email", name="uq_meeting_guest_email"),
        CheckConstraint("attendee_type IN ('staff','guest','speaker','secretary','chairperson','member_delegate')", name="ck_meeting_guest_type"),
        CheckConstraint("registration_source IN ('qr','admin')", name="ck_meeting_guest_registration_source"),
        CheckConstraint("attendance_status IN ('registered','present','absent','excused')", name="ck_meeting_guest_attendance"),
        CheckConstraint("(gps_latitude IS NULL AND gps_longitude IS NULL) OR (gps_latitude IS NOT NULL AND gps_longitude IS NOT NULL)", name="ck_meeting_guest_gps_pair"),
        CheckConstraint("gps_latitude IS NULL OR gps_latitude BETWEEN -90 AND 90", name="ck_meeting_guest_gps_latitude"),
        CheckConstraint("gps_longitude IS NULL OR gps_longitude BETWEEN -180 AND 180", name="ck_meeting_guest_gps_longitude"),
        CheckConstraint("gps_accuracy_m IS NULL OR gps_accuracy_m BETWEEN 0 AND 100000", name="ck_meeting_guest_gps_accuracy"),
        CheckConstraint("signature_png IS NULL OR length(signature_png) BETWEEN 1 AND 98304", name="ck_meeting_guest_signature_size"),
        Index("ix_meeting_guest_registration", "meeting_id", "registered_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    meeting_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("meetings.id", ondelete="RESTRICT"), index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320))
    phone: Mapped[str] = mapped_column(String(24))
    attendee_type: Mapped[str] = mapped_column(String(16))
    organization: Mapped[str | None] = mapped_column(String(200), nullable=True)
    signature_png: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    gps_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    gps_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    gps_accuracy_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    gps_captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    registration_source: Mapped[str] = mapped_column(String(8), default="qr", server_default="qr")
    registered_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    attendance_status: Mapped[str] = mapped_column(String(16), default="registered", server_default="registered")
    attendance_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    recorded_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def signature_present(self) -> bool:
        return self.signature_png is not None


class MeetingAttachment(Base):
    __tablename__ = "meeting_attachments"
    __table_args__ = (CheckConstraint("size_bytes > 0", name="ck_meeting_attachment_size_positive"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    meeting_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("meetings.id", ondelete="RESTRICT"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(Integer)
    content_sha256: Mapped[str] = mapped_column(String(64))
    content: Mapped[bytes] = mapped_column(LargeBinary)
    uploaded_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MeetingMinutesRevision(Base):
    __tablename__ = "meeting_minutes_revisions"
    __table_args__ = (
        UniqueConstraint("meeting_id", "revision", name="uq_meeting_minutes_revision"),
        CheckConstraint("revision > 0", name="ck_meeting_minutes_revision_positive"),
        CheckConstraint("status IN ('draft','submitted','approved','rejected')", name="ck_meeting_minutes_status"),
        Index("ix_meeting_minutes_status", "meeting_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    meeting_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("meetings.id", ondelete="RESTRICT"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="draft", server_default="draft")
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approval_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MeetingDecision(Base):
    __tablename__ = "meeting_decisions"
    __table_args__ = (
        UniqueConstraint("meeting_id", "decision_number", name="uq_meeting_decision_number"),
        CheckConstraint("decision_number > 0", name="ck_meeting_decision_number_positive"),
        CheckConstraint("status IN ('proposed','adopted','rejected')", name="ck_meeting_decision_status"),
        Index("ix_meeting_decisions_meeting_status", "meeting_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    meeting_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("meetings.id", ondelete="RESTRICT"), index=True)
    decision_number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    details: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="proposed", server_default="proposed")
    proposed_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MeetingActionItem(Base):
    __tablename__ = "meeting_action_items"
    __table_args__ = (
        CheckConstraint("status IN ('open','in_progress','completed','cancelled')", name="ck_meeting_action_status"),
        Index("ix_meeting_action_items_meeting_status", "meeting_id", "status"),
        Index("ix_meeting_action_items_assignee_due", "assigned_to_id", "due_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    meeting_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("meetings.id", ondelete="RESTRICT"), index=True)
    decision_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("meeting_decisions.id", ondelete="RESTRICT"), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    assigned_to_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="open", server_default="open")
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MeetingActionHistory(Base):
    __tablename__ = "meeting_action_history"
    __table_args__ = (
        CheckConstraint("to_status IN ('open','in_progress','completed','cancelled')", name="ck_meeting_action_history_status"),
        Index("ix_meeting_action_history_item_time", "action_item_id", "changed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    action_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("meeting_action_items.id", ondelete="RESTRICT"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_status: Mapped[str] = mapped_column(String(16))
    changed_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
