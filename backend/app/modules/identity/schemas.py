from uuid import UUID
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=72)
    workspace_name: str = Field(min_length=1, max_length=160)

    @field_validator("password")
    @classmethod
    def password_fits_bcrypt(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must be no more than 72 UTF-8 bytes")
        return value

    @field_validator("workspace_name")
    @classmethod
    def workspace_name_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Workspace name cannot be blank")
        return value.strip()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetComplete(BaseModel):
    token: str = Field(min_length=32, max_length=100)
    password: str = Field(min_length=12, max_length=72)

    @field_validator("password")
    @classmethod
    def password_fits_bcrypt(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must be no more than 72 UTF-8 bytes")
        return value


class PasswordResetAccepted(BaseModel):
    message: str


class EmailVerificationRequest(BaseModel):
    email: EmailStr


class EmailVerificationTokenRequest(BaseModel):
    token: str = Field(min_length=32, max_length=100)


class UserResponse(BaseModel):
    id: UUID
    email: EmailStr


class WorkspaceResponse(BaseModel):
    id: UUID
    name: str
    role: str | None = None


class RegistrationResponse(BaseModel):
    user: UserResponse
    workspace: WorkspaceResponse


class WorkspaceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)

    @field_validator("name")
    @classmethod
    def name_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Workspace name cannot be blank")
        return value.strip()


class WorkspaceDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str


class InvitationCreateRequest(BaseModel):
    email: EmailStr
    role: str = "member"


class InvitationResponse(BaseModel):
    id: UUID
    email: EmailStr
    role: str
    status: str
    expires_at: datetime
    created_at: datetime


class InvitationTokenRequest(BaseModel):
    token: str = Field(min_length=32, max_length=100)


class InvitationInfoResponse(BaseModel):
    email: EmailStr
    role: str
    workspace_name: str
    expires_at: datetime


class InvitationAcceptRequest(InvitationTokenRequest):
    password: str = Field(min_length=12, max_length=72)

    @field_validator("password")
    @classmethod
    def password_fits_bcrypt(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must be no more than 72 UTF-8 bytes")
        return value


class InvitationAcceptResponse(BaseModel):
    user: UserResponse
    workspace: WorkspaceResponse
