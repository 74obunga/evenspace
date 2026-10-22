from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.modules.identity.models import AuthSession, User, Workspace, WorkspaceMembership, WorkspaceRole
from app.modules.identity.security import token_hash, tokens_match


@dataclass
class AuthContext:
    session: AuthSession
    user: User


def get_auth_context(request: Request, db: Session = Depends(get_db)) -> AuthContext:
    raw_token = request.cookies.get(get_settings().session_cookie_name)
    if not raw_token:
        raise HTTPException(status_code=401, detail="Authentication required")

    auth_session = db.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == token_hash(raw_token),
            AuthSession.expires_at > datetime.now(timezone.utc),
            AuthSession.revoked_at.is_(None),
        )
    )
    if auth_session is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return AuthContext(session=auth_session, user=auth_session.user)


def require_csrf(request: Request, context: AuthContext = Depends(get_auth_context)) -> AuthContext:
    settings = get_settings()
    cookie_token = request.cookies.get(settings.csrf_cookie_name, "")
    header_token = request.headers.get("X-CSRF-Token", "")
    if not cookie_token or not tokens_match(cookie_token, header_token):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    if not tokens_match(context.session.csrf_token_hash, token_hash(cookie_token)):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    return context


def get_workspace_for_member(
    workspace_id: UUID,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> Workspace:
    workspace = db.scalar(
        select(Workspace)
        .join(WorkspaceMembership, WorkspaceMembership.workspace_id == Workspace.id)
        .where(Workspace.id == workspace_id, WorkspaceMembership.user_id == context.user.id)
    )
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


def require_workspace_manager(
    workspace_id: UUID,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> AuthContext:
    membership = db.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == context.user.id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if membership.role not in {WorkspaceRole.OWNER, WorkspaceRole.ADMIN}:
        raise HTTPException(status_code=403, detail="Workspace administrator access required")
    return context


def require_workspace_event_manager(
    workspace_id: UUID,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> AuthContext:
    membership = db.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == context.user.id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if membership.role not in {WorkspaceRole.OWNER, WorkspaceRole.ADMIN, WorkspaceRole.EVENT_MANAGER}:
        raise HTTPException(status_code=403, detail="Event manager access required")
    return context
