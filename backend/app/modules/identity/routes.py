from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.modules.identity.dependencies import AuthContext, get_auth_context, get_workspace_for_member, require_csrf, require_workspace_manager
from app.modules.identity.models import Workspace, WorkspaceInvitation, WorkspaceMembership
from app.modules.identity.schemas import (
    LoginRequest,
    PasswordResetAccepted,
    PasswordResetComplete,
    PasswordResetRequest,
    EmailVerificationRequest,
    EmailVerificationTokenRequest,
    RegisterRequest,
    RegistrationResponse,
    UserResponse,
    WorkspaceCreateRequest,
    WorkspaceDetailResponse,
    WorkspaceResponse,
    InvitationCreateRequest, InvitationResponse, InvitationTokenRequest, InvitationInfoResponse,
    InvitationAcceptRequest, InvitationAcceptResponse,
)
from app.modules.identity.service import (
    EmailAlreadyRegistered,
    EmailNotVerified,
    EmailVerificationUnavailable,
    InvalidEmailVerification,
    InvalidCredentials,
    LoginRateLimited,
    InvalidPasswordReset,
    PasswordResetUnavailable,
    complete_password_reset,
    complete_email_verification,
    create_workspace,
    list_workspaces,
    login,
    register,
    request_password_reset,
    request_email_verification,
    create_workspace_invitation, list_workspace_invitations, revoke_workspace_invitation,
    get_invitation_info, accept_workspace_invitation, InvitationUnavailable, InvalidInvitation,
    InvitationConflict,
    InvitationForbidden,
    revoke_session,
)

auth_router = APIRouter(prefix="/auth", tags=["authentication"])
workspace_router = APIRouter(prefix="/workspaces", tags=["workspaces"])


def _set_session_cookies(response: Response, session_token: str, csrf_token: str) -> None:
    settings = get_settings()
    common = {
        "max_age": settings.session_ttl_seconds,
        "secure": settings.session_cookie_secure,
        "samesite": "lax",
        "path": "/",
    }
    response.set_cookie(settings.session_cookie_name, session_token, httponly=True, **common)
    response.set_cookie(settings.csrf_cookie_name, csrf_token, httponly=False, **common)


def _clear_session_cookies(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(settings.session_cookie_name, path="/", secure=settings.session_cookie_secure,
                           httponly=True, samesite="lax")
    response.delete_cookie(settings.csrf_cookie_name, path="/", secure=settings.session_cookie_secure,
                           httponly=False, samesite="lax")


def _check_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin is None:
        return
    allowed = {*get_settings().frontend_origins, str(request.base_url).rstrip("/")}
    if origin.rstrip("/") not in allowed:
        raise HTTPException(status_code=403, detail="Origin is not allowed")


@auth_router.post("/register", response_model=RegistrationResponse, status_code=201)
def register_endpoint(payload: RegisterRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    _check_origin(request)
    try:
        user, workspace = register(
            db, payload.email, payload.password, payload.workspace_name
        )
    except EmailAlreadyRegistered:
        raise HTTPException(status_code=409, detail="An account with this email already exists") from None
    except EmailVerificationUnavailable:
        raise HTTPException(status_code=503, detail="Email verification is temporarily unavailable") from None
    _clear_session_cookies(response)
    return RegistrationResponse(
        user=UserResponse(id=user.id, email=user.email),
        workspace=WorkspaceResponse(id=workspace.id, name=workspace.name, role="owner"),
    )


@auth_router.post("/login", response_model=UserResponse)
def login_endpoint(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    _check_origin(request)
    try:
        user, _auth_session, session_token, csrf_token = login(
            db, payload.email, payload.password, request.client.host if request.client else "unknown"
        )
    except InvalidCredentials:
        raise HTTPException(status_code=401, detail="Invalid email or password") from None
    except LoginRateLimited:
        raise HTTPException(status_code=429, detail="Too many failed sign-in attempts. Try again later.") from None
    except EmailNotVerified:
        raise HTTPException(status_code=403, detail="Verify your email before signing in. Request another verification link if needed.") from None
    _set_session_cookies(response, session_token, csrf_token)
    return UserResponse(id=user.id, email=user.email)


@auth_router.post("/password-reset/request", response_model=PasswordResetAccepted)
def request_password_reset_endpoint(payload: PasswordResetRequest, request: Request,
                                   db: Session = Depends(get_db)):
    _check_origin(request)
    try:
        request_password_reset(db, str(payload.email))
    except PasswordResetUnavailable:
        raise HTTPException(status_code=503, detail="Password reset email is temporarily unavailable") from None
    return PasswordResetAccepted(message="If an account exists for that email, a reset link will be sent shortly.")


@auth_router.post("/password-reset/complete", response_model=PasswordResetAccepted)
def complete_password_reset_endpoint(payload: PasswordResetComplete, request: Request,
                                     db: Session = Depends(get_db)):
    _check_origin(request)
    try:
        complete_password_reset(db, payload.token, payload.password)
    except InvalidPasswordReset:
        raise HTTPException(status_code=400, detail="This password reset link is invalid or expired") from None
    return PasswordResetAccepted(message="Password updated. You can now sign in.")


@auth_router.post("/email-verification/request", response_model=PasswordResetAccepted)
def request_email_verification_endpoint(payload: EmailVerificationRequest, request: Request,
                                        db: Session = Depends(get_db)):
    _check_origin(request)
    try:
        request_email_verification(db, str(payload.email))
    except EmailVerificationUnavailable:
        raise HTTPException(status_code=503, detail="Email verification is temporarily unavailable") from None
    return PasswordResetAccepted(message="If the account needs verification, a link will be sent shortly.")


@auth_router.post("/email-verification/complete", response_model=PasswordResetAccepted)
def complete_email_verification_endpoint(payload: EmailVerificationTokenRequest, request: Request,
                                         db: Session = Depends(get_db)):
    _check_origin(request)
    try:
        complete_email_verification(db, payload.token)
    except InvalidEmailVerification:
        raise HTTPException(status_code=400, detail="This verification link is invalid or expired") from None
    return PasswordResetAccepted(message="Email verified. You can now sign in.")


@auth_router.post("/invitations/info", response_model=InvitationInfoResponse)
def invitation_info_endpoint(payload: InvitationTokenRequest, db: Session = Depends(get_db)):
    try:
        invitation, workspace = get_invitation_info(db, payload.token)
    except InvalidInvitation:
        raise HTTPException(status_code=400, detail="This invitation link is invalid or expired") from None
    return InvitationInfoResponse(email=invitation.email, role=invitation.role.value,
                                  workspace_name=workspace.name, expires_at=invitation.expires_at)


@auth_router.post("/invitations/accept", response_model=InvitationAcceptResponse)
def accept_invitation_endpoint(payload: InvitationAcceptRequest, request: Request, response: Response,
                              db: Session = Depends(get_db)):
    _check_origin(request)
    try:
        user, workspace, session_token, csrf_token = accept_workspace_invitation(db, payload.token, payload.password)
    except InvalidCredentials:
        raise HTTPException(status_code=401, detail="The password does not match this email account") from None
    except InvalidInvitation:
        raise HTTPException(status_code=400, detail="This invitation link is invalid or expired, or the account is already a workspace member") from None
    _set_session_cookies(response, session_token, csrf_token)
    role = db.scalar(select(WorkspaceMembership.role).where(
        WorkspaceMembership.workspace_id == workspace.id, WorkspaceMembership.user_id == user.id,
    ))
    return InvitationAcceptResponse(user=UserResponse(id=user.id, email=user.email),
                                    workspace=WorkspaceResponse(id=workspace.id, name=workspace.name, role=role.value))


@auth_router.get("/me", response_model=UserResponse)
def current_user(context: AuthContext = Depends(get_auth_context)):
    return UserResponse(id=context.user.id, email=context.user.email)


@auth_router.post("/logout", status_code=204)
def logout(context: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)):
    revoke_session(db, context.session)
    response = Response(status_code=204)
    _clear_session_cookies(response)
    return response


@workspace_router.get("", response_model=list[WorkspaceResponse])
def get_workspaces(context: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)):
    return [
        WorkspaceResponse(id=workspace.id, name=workspace.name, role=role.value)
        for workspace, role in list_workspaces(db, context.user.id)
    ]


@workspace_router.post("", response_model=WorkspaceResponse, status_code=201)
def post_workspace(
    payload: WorkspaceCreateRequest,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    workspace, role = create_workspace(db, context.user.id, payload.name)
    return WorkspaceResponse(id=workspace.id, name=workspace.name, role=role.value)


@workspace_router.get("/{workspace_id}", response_model=WorkspaceDetailResponse)
def get_workspace(workspace: Workspace = Depends(get_workspace_for_member)):
    return workspace


@workspace_router.get("/{workspace_id}/invitations", response_model=list[InvitationResponse])
def get_invitations(workspace_id: UUID, _context: AuthContext = Depends(require_workspace_manager),
                    db: Session = Depends(get_db)):
    return [InvitationResponse(id=row.id, email=row.email, role=row.role.value, status=status,
                               expires_at=row.expires_at, created_at=row.created_at)
            for row, status in list_workspace_invitations(db, workspace_id)]


@workspace_router.post("/{workspace_id}/invitations", response_model=InvitationResponse, status_code=201)
def post_invitation(workspace_id: UUID, payload: InvitationCreateRequest, request: Request,
                    context: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)):
    _check_origin(request)
    try:
        row = create_workspace_invitation(db, workspace_id, context.user.id, str(payload.email), payload.role)
    except InvitationUnavailable:
        raise HTTPException(status_code=503, detail="Invitation email is temporarily unavailable") from None
    except InvitationForbidden:
        raise HTTPException(status_code=403, detail="Workspace administrator access required") from None
    except InvitationConflict:
        raise HTTPException(status_code=409, detail="This invitation role is not allowed or the email is already a member or has a pending invitation") from None
    return InvitationResponse(id=row.id, email=row.email, role=row.role.value, status="pending",
                              expires_at=row.expires_at, created_at=row.created_at)


@workspace_router.delete("/{workspace_id}/invitations/{invitation_id}", status_code=204)
def delete_invitation(workspace_id: UUID, invitation_id: UUID, request: Request,
                      _context: AuthContext = Depends(require_csrf),
                      _manager: AuthContext = Depends(require_workspace_manager), db: Session = Depends(get_db)):
    _check_origin(request)
    if not revoke_workspace_invitation(db, workspace_id, invitation_id):
        raise HTTPException(status_code=404, detail="Invitation not found")
    return Response(status_code=204)

