from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    kind: str
    recipient_email: str
    template_key: str
    status: str
    attempt_count: int
    last_error: str | None
    created_at: datetime
    sent_at: datetime | None


class NotificationAttemptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    attempt_number: int
    status: str
    error: str | None
    attempted_at: datetime


class TemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    key: str
    channel: str
    subject_template: str
    body_template: str
    enabled: bool


class TemplateUpdate(BaseModel):
    subject_template: str = Field(min_length=1, max_length=300)
    body_template: str = Field(min_length=1, max_length=20000)
    enabled: bool = True
