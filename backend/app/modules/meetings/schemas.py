from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class MeetingCreate(BaseModel):
    event_id: UUID
    meeting_type: str = Field(min_length=1, max_length=80)
    chairperson_id: UUID | None = None

    @field_validator("meeting_type")
    @classmethod
    def non_blank_type(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Meeting type cannot be blank")
        return value.strip()


class MeetingScheduleCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10000)
    meeting_type: str = Field(min_length=1, max_length=80)
    start_at: datetime
    end_at: datetime
    timezone: str = Field(min_length=1, max_length=80)
    meeting_mode: Literal["physical", "online"] = "physical"
    online_url: str | None = Field(default=None, max_length=500)

    @field_validator("title", "meeting_type", "timezone")
    @classmethod
    def non_blank_schedule_fields(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("This field cannot be blank")
        return value.strip()

    @field_validator("start_at", "end_at")
    @classmethod
    def aware_schedule_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Meeting times must include a UTC offset")
        return value

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @field_validator("online_url")
    @classmethod
    def valid_online_url(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower()
        allowed = host == "meet.google.com" or host == "zoom.us" or host.endswith(".zoom.us")
        if parsed.scheme != "https" or not allowed:
            raise ValueError("Use a secure Google Meet or Zoom link")
        return value

    @model_validator(mode="after")
    def valid_meeting_schedule(self):
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Use a valid IANA timezone") from exc
        if self.end_at <= self.start_at:
            raise ValueError("Meeting end must be after its start")
        if self.meeting_mode == "online" and not self.online_url:
            raise ValueError("Add a Google Meet or Zoom link for online meetings")
        if self.meeting_mode == "physical" and self.online_url:
            raise ValueError("Online meeting link is only used for online meetings")
        return self


class MeetingResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    event_id: UUID
    meeting_type: str
    meeting_mode: str = "physical"
    online_url: str | None = None
    chairperson_id: UUID | None
    status: str
    cancellation_reason: str | None
    created_at: datetime


class MeetingStatusChange(BaseModel):
    status: Literal["scheduled", "held", "cancelled"]
    note: str | None = Field(default=None, max_length=500)


class AgendaItemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    presenter_id: UUID | None = None
    duration_minutes: int | None = Field(default=None, ge=1, le=1440)

    @field_validator("title")
    @classmethod
    def non_blank_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Agenda title cannot be blank")
        return value.strip()


class AgendaItemResponse(BaseModel):
    id: UUID
    meeting_id: UUID
    position: int
    title: str
    description: str | None
    presenter_id: UUID | None
    duration_minutes: int | None


class InviteeCreate(BaseModel):
    user_id: UUID


class AttendanceChange(BaseModel):
    status: Literal["present", "absent", "excused"]
    note: str | None = Field(default=None, max_length=500)


class InviteeResponse(BaseModel):
    id: UUID
    meeting_id: UUID
    user_id: UUID
    invited_by_id: UUID
    invited_at: datetime
    attendance_status: str
    attendance_note: str | None
    recorded_by_id: UUID | None
    recorded_at: datetime | None


class MeetingJoinLinkResponse(BaseModel):
    meeting_id: UUID
    token: str


class MeetingJoinInfo(BaseModel):
    meeting_id: UUID
    meeting_type: str
    event_title: str
    starts_at: datetime
    timezone: str
    meeting_mode: str = "physical"


class MeetingJoinTokenRequest(BaseModel):
    token: str = Field(min_length=32, max_length=100)


class MeetingGuestRegistrationCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    phone: str = Field(min_length=7, max_length=24)
    attendee_type: Literal["staff", "guest"]
    organization: str | None = Field(default=None, max_length=200)
    token: str = Field(min_length=32, max_length=100)

    @field_validator("full_name")
    @classmethod
    def non_blank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Name cannot be blank")
        return value.strip()

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().casefold()

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str) -> str:
        normalized = value.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
        digits = normalized[1:] if normalized.startswith("+") else normalized
        if not digits.isdigit() or not 7 <= len(digits) <= 15:
            raise ValueError("Enter a valid phone number including country code")
        return normalized

    @field_validator("organization")
    @classmethod
    def normalize_organization(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class MeetingGuestRegistrationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    meeting_id: UUID
    full_name: str
    email: EmailStr
    phone: str
    attendee_type: str
    organization: str | None
    attendance_status: str
    attendance_note: str | None = None
    recorded_by_id: UUID | None = None
    recorded_at: datetime | None = None
    registered_at: datetime


class MeetingGuestJoinResponse(BaseModel):
    registration: MeetingGuestRegistrationResponse
    join_url: str | None = None


class MeetingGuestAttendanceChange(BaseModel):
    status: Literal["present", "absent", "excused"]
    note: str | None = Field(default=None, max_length=500)


class AttachmentResponse(BaseModel):
    id: UUID
    meeting_id: UUID
    filename: str
    media_type: str
    size_bytes: int
    content_sha256: str
    uploaded_by_id: UUID
    created_at: datetime


class MinutesCreate(BaseModel):
    content: str = Field(min_length=1, max_length=100000)

    @field_validator("content")
    @classmethod
    def non_blank_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Minutes content cannot be blank")
        return value.strip()


class MinutesDecision(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class MinutesResponse(BaseModel):
    id: UUID
    meeting_id: UUID
    revision: int
    content: str
    status: str
    created_by_id: UUID
    submitted_at: datetime | None
    approved_by_id: UUID | None
    approved_at: datetime | None
    approval_note: str | None
    created_at: datetime


class DecisionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    details: str = Field(min_length=1, max_length=10000)

    @field_validator("title", "details")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Decision title and details cannot be blank")
        return value.strip()


class DecisionResolve(BaseModel):
    result: Literal["adopted", "rejected"]
    note: str | None = Field(default=None, max_length=500)


class DecisionResponse(BaseModel):
    id: UUID
    meeting_id: UUID
    decision_number: int
    title: str
    details: str
    status: str
    proposed_by_id: UUID
    resolved_by_id: UUID | None
    resolved_at: datetime | None
    resolution_note: str | None


class ActionItemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    details: str | None = Field(default=None, max_length=10000)
    assigned_to_id: UUID | None = None
    due_at: datetime | None = None
    decision_id: UUID | None = None

    @field_validator("title")
    @classmethod
    def non_blank_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Action item title cannot be blank")
        return value.strip()

    @field_validator("due_at")
    @classmethod
    def aware_due_at(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Due date must include a UTC offset")
        return value


class ActionStatusChange(BaseModel):
    status: Literal["open", "in_progress", "completed", "cancelled"]
    note: str | None = Field(default=None, max_length=500)


class ActionItemResponse(BaseModel):
    id: UUID
    meeting_id: UUID
    decision_id: UUID | None
    title: str
    details: str | None
    assigned_to_id: UUID | None
    due_at: datetime | None
    status: str
    created_by_id: UUID
    completed_at: datetime | None


class ActionHistoryResponse(BaseModel):
    id: UUID
    action_item_id: UUID
    from_status: str | None
    to_status: str
    changed_by_id: UUID
    note: str | None
    changed_at: datetime
