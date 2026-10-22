from datetime import datetime, timedelta, timezone
from hashlib import sha256
import secrets
from uuid import UUID

from sqlalchemy import case, delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.identity.models import AuthSession, EmailVerificationToken, LoginAttemptBucket, PasswordResetToken, User, Workspace, WorkspaceInvitation, WorkspaceMembership, WorkspaceRole
from app.modules.identity.security import hash_password, new_csrf_token, new_session_token, token_hash, verify_password
from app.modules.notifications.service import enqueue_notification, secret_notifications_ready


class EmailAlreadyRegistered(Exception):
    pass


class InvalidCredentials(Exception):
    pass


class LoginRateLimited(Exception):
    pass


class PasswordResetUnavailable(Exception):
    pass


class InvalidPasswordReset(Exception):
    pass


class EmailVerificationUnavailable(Exception):
    pass


class EmailNotVerified(Exception):
    pass


class InvalidEmailVerification(Exception):
    pass


class InvitationUnavailable(Exception):
    pass


class InvalidInvitation(Exception):
    pass


class InvitationConflict(Exception):
    pass


class InvitationForbidden(Exception):
    pass


# Used to keep failed logins for unknown and existing accounts at comparable cost.
_DUMMY_PASSWORD_HASH = hash_password("not-a-real-evenSpace-password")


def _normalized_email(email: str) -> str:
    return email.strip().casefold()


def register(db: Session, email: str, password: str, workspace_name: str) -> tuple[User, Workspace]:
    if not secret_notifications_ready():
        raise EmailVerificationUnavailable
    user = User(email=_normalized_email(email), password_hash=hash_password(password))
    workspace = Workspace(name=workspace_name.strip())
    try:
        db.add_all([user, workspace])
        db.flush()
        db.add(WorkspaceMembership(user_id=user.id, workspace_id=workspace.id, role=WorkspaceRole.OWNER))
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        verification = EmailVerificationToken(
            user_id=user.id,
            token_hash=sha256(token.encode("ascii")).hexdigest(),
            expires_at=now + timedelta(hours=24),
        )
        db.add(verification)
        db.flush()
        settings = get_settings()
        enqueue_notification(
            db, workspace_id=workspace.id, kind="email_verification", recipient_email=user.email,
            template_key="email_verification", context={},
            secret_context={"verification_url": f"{settings.frontend_origin.rstrip('/')}/#verify-email/{token}"},
            dedupe_key=f"email-verification:{verification.id}",
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise EmailAlreadyRegistered from exc
    except ValueError:
        db.rollback()
        raise EmailVerificationUnavailable from None
    return user, workspace


def _new_session(user_id: UUID) -> tuple[AuthSession, str, str]:
    raw_session = new_session_token()
    raw_csrf = new_csrf_token()
    auth_session = AuthSession(
        user_id=user_id,
        token_hash=token_hash(raw_session),
        csrf_token_hash=token_hash(raw_csrf),
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=get_settings().session_ttl_seconds),
    )
    return auth_session, raw_session, raw_csrf


def _login_key(email: str, client_ip: str) -> str:
    import hashlib

    return hashlib.sha256(f"{_normalized_email(email)}\0{client_ip}".encode("utf-8")).hexdigest()


def _is_rate_limited(db: Session, key: str, now: datetime) -> bool:
    window_start = now - timedelta(minutes=15)
    failures = db.scalar(
        select(LoginAttemptBucket.failed_attempts).where(
            LoginAttemptBucket.key == key,
            LoginAttemptBucket.window_started_at > window_start,
        )
    )
    return bool(failures and failures >= 5)


def _record_failed_login(db: Session, key: str, now: datetime) -> None:
    window_start = now - timedelta(minutes=15)
    values = {"key": key, "window_started_at": now, "failed_attempts": 1}
    reset = LoginAttemptBucket.window_started_at <= window_start
    update = {
        "window_started_at": case((reset, now), else_=LoginAttemptBucket.window_started_at),
        "failed_attempts": case((reset, 1), else_=LoginAttemptBucket.failed_attempts + 1),
    }
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        statement = pg_insert(LoginAttemptBucket).values(**values).on_conflict_do_update(
            index_elements=[LoginAttemptBucket.key], set_=update
        )
    elif dialect == "sqlite":
        statement = sqlite_insert(LoginAttemptBucket).values(**values).on_conflict_do_update(
            index_elements=[LoginAttemptBucket.key], set_=update
        )
    else:
        bucket = db.get(LoginAttemptBucket, key)
        if bucket is None:
            db.add(LoginAttemptBucket(**values))
        elif bucket.window_started_at <= window_start:
            bucket.window_started_at, bucket.failed_attempts = now, 1
        else:
            bucket.failed_attempts += 1
        db.commit()
        return
    db.execute(statement)
    db.commit()


def login(db: Session, email: str, password: str, client_ip: str) -> tuple[User, AuthSession, str, str]:
    now = datetime.now(timezone.utc)
    key = _login_key(email, client_ip)
    if _is_rate_limited(db, key, now):
        raise LoginRateLimited

    user = db.scalar(select(User).where(User.email == _normalized_email(email)))
    if user is None:
        verify_password(password, _DUMMY_PASSWORD_HASH)
        _record_failed_login(db, key, now)
        raise InvalidCredentials
    if not verify_password(password, user.password_hash):
        _record_failed_login(db, key, now)
        raise InvalidCredentials
    if user.email_verified_at is None:
        raise EmailNotVerified

    db.execute(delete(LoginAttemptBucket).where(LoginAttemptBucket.key == key))
    auth_session, raw_session, raw_csrf = _new_session(user.id)
    db.add(auth_session)
    db.commit()
    return user, auth_session, raw_session, raw_csrf


def request_password_reset(db: Session, email: str) -> None:
    if not secret_notifications_ready():
        raise PasswordResetUnavailable
    now = datetime.now(timezone.utc)
    normalized = _normalized_email(email)
    user = db.scalar(select(User).where(User.email == normalized))
    if user is None:
        return
    recent = db.scalar(select(PasswordResetToken.id).where(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.created_at >= now - timedelta(minutes=5),
    ).limit(1))
    if recent is not None:
        return
    workspace_id = db.scalar(select(WorkspaceMembership.workspace_id).where(
        WorkspaceMembership.user_id == user.id,
    ).order_by(WorkspaceMembership.created_at).limit(1))
    if workspace_id is None:
        return

    db.execute(update(PasswordResetToken).where(
        PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None),
    ).values(used_at=now))
    token = secrets.token_urlsafe(32)
    row = PasswordResetToken(
        user_id=user.id,
        token_hash=sha256(token.encode("ascii")).hexdigest(),
        expires_at=now + timedelta(minutes=30),
    )
    db.add(row)
    db.flush()
    settings = get_settings()
    try:
        enqueue_notification(
            db, workspace_id=workspace_id, kind="password_reset", recipient_email=user.email,
            template_key="password_reset", context={},
            secret_context={"reset_url": f"{settings.frontend_origin.rstrip('/')}/#reset-password/{token}"},
            dedupe_key=f"password-reset:{row.id}",
        )
        db.commit()
    except (ValueError, IntegrityError):
        db.rollback()
        raise PasswordResetUnavailable from None


def request_email_verification(db: Session, email: str) -> None:
    if not secret_notifications_ready():
        raise EmailVerificationUnavailable
    now = datetime.now(timezone.utc)
    user = db.scalar(select(User).where(User.email == _normalized_email(email)))
    if user is None or user.email_verified_at is not None:
        return
    recent = db.scalar(select(EmailVerificationToken.id).where(
        EmailVerificationToken.user_id == user.id,
        EmailVerificationToken.created_at >= now - timedelta(minutes=5),
    ).limit(1))
    if recent is not None:
        return
    workspace_id = db.scalar(select(WorkspaceMembership.workspace_id).where(
        WorkspaceMembership.user_id == user.id,
    ).order_by(WorkspaceMembership.created_at).limit(1))
    if workspace_id is None:
        return
    db.execute(update(EmailVerificationToken).where(
        EmailVerificationToken.user_id == user.id,
        EmailVerificationToken.used_at.is_(None),
    ).values(used_at=now))
    token = secrets.token_urlsafe(32)
    row = EmailVerificationToken(
        user_id=user.id, token_hash=sha256(token.encode("ascii")).hexdigest(),
        expires_at=now + timedelta(hours=24),
    )
    db.add(row)
    db.flush()
    settings = get_settings()
    try:
        enqueue_notification(
            db, workspace_id=workspace_id, kind="email_verification", recipient_email=user.email,
            template_key="email_verification", context={},
            secret_context={"verification_url": f"{settings.frontend_origin.rstrip('/')}/#verify-email/{token}"},
            dedupe_key=f"email-verification:{row.id}",
        )
        db.commit()
    except (ValueError, IntegrityError):
        db.rollback()
        raise EmailVerificationUnavailable from None


def complete_email_verification(db: Session, token: str) -> None:
    digest = sha256(token.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)
    verification = db.scalar(select(EmailVerificationToken).where(
        EmailVerificationToken.token_hash == digest,
    ).with_for_update())
    if verification is None or verification.used_at is not None:
        raise InvalidEmailVerification
    expires_at = verification.expires_at if verification.expires_at.tzinfo else verification.expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now:
        raise InvalidEmailVerification
    user = db.get(User, verification.user_id, with_for_update=True)
    if user is None:
        raise InvalidEmailVerification
    user.email_verified_at = now
    db.execute(update(EmailVerificationToken).where(
        EmailVerificationToken.user_id == user.id,
        EmailVerificationToken.used_at.is_(None),
    ).values(used_at=now))
    db.commit()


def complete_password_reset(db: Session, token: str, password: str) -> None:
    digest = sha256(token.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)
    reset = db.scalar(select(PasswordResetToken).where(
        PasswordResetToken.token_hash == digest,
    ).with_for_update())
    if reset is None or reset.used_at is not None:
        raise InvalidPasswordReset
    expires_at = reset.expires_at if reset.expires_at.tzinfo else reset.expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now:
        raise InvalidPasswordReset
    user = db.get(User, reset.user_id, with_for_update=True)
    if user is None:
        raise InvalidPasswordReset
    user.password_hash = hash_password(password)
    user.email_verified_at = user.email_verified_at or now
    db.execute(update(PasswordResetToken).where(
        PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None),
    ).values(used_at=now))
    db.execute(update(AuthSession).where(
        AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None),
    ).values(revoked_at=now))
    db.commit()


def revoke_session(db: Session, auth_session: AuthSession) -> None:
    auth_session.revoked_at = datetime.now(timezone.utc)
    db.commit()


def list_workspaces(db: Session, user_id: UUID) -> list[tuple[Workspace, WorkspaceRole]]:
    rows = db.execute(
        select(Workspace, WorkspaceMembership.role)
        .join(WorkspaceMembership, WorkspaceMembership.workspace_id == Workspace.id)
        .where(WorkspaceMembership.user_id == user_id)
        .order_by(Workspace.name)
    )
    return list(rows.tuples())


def create_workspace(db: Session, user_id: UUID, name: str) -> tuple[Workspace, WorkspaceRole]:
    workspace = Workspace(name=name.strip())
    db.add(workspace)
    db.flush()
    membership = WorkspaceMembership(workspace_id=workspace.id, user_id=user_id, role=WorkspaceRole.OWNER)
    db.add(membership)
    db.commit()
    return workspace, membership.role


def create_workspace_invitation(db: Session, workspace_id: UUID, actor_id: UUID, email: str, role_name: str) -> WorkspaceInvitation:
    if not secret_notifications_ready():
        raise InvitationUnavailable
    actor = db.scalar(select(WorkspaceMembership).where(
        WorkspaceMembership.workspace_id == workspace_id, WorkspaceMembership.user_id == actor_id,
    ))
    try:
        role = WorkspaceRole(role_name)
    except ValueError:
        raise InvitationConflict from None
    if actor is None or actor.role not in {WorkspaceRole.OWNER, WorkspaceRole.ADMIN}:
        raise InvitationForbidden
    if role == WorkspaceRole.OWNER or (actor.role == WorkspaceRole.ADMIN and role == WorkspaceRole.ADMIN):
        raise InvitationConflict
    normalized = _normalized_email(email)
    user = db.scalar(select(User).where(User.email == normalized))
    if user and db.scalar(select(WorkspaceMembership.id).where(
        WorkspaceMembership.workspace_id == workspace_id, WorkspaceMembership.user_id == user.id,
    )):
        raise InvitationConflict
    now = datetime.now(timezone.utc)
    pending = db.scalar(select(WorkspaceInvitation).where(
        WorkspaceInvitation.workspace_id == workspace_id, WorkspaceInvitation.email == normalized,
        WorkspaceInvitation.accepted_at.is_(None), WorkspaceInvitation.revoked_at.is_(None),
        WorkspaceInvitation.expires_at > now,
    ))
    if pending:
        raise InvitationConflict
    token = secrets.token_urlsafe(32)
    invitation = WorkspaceInvitation(
        workspace_id=workspace_id, email=normalized, role=role,
        token_hash=sha256(token.encode("ascii")).hexdigest(), invited_by_id=actor_id,
        expires_at=now + timedelta(days=7),
    )
    db.add(invitation)
    db.flush()
    workspace = db.get(Workspace, workspace_id)
    settings = get_settings()
    try:
        enqueue_notification(
            db, workspace_id=workspace_id, kind="workspace_invitation", recipient_email=normalized,
            template_key="workspace_invitation", context={"workspace_name": workspace.name, "role": role.value},
            secret_context={"invitation_url": f"{settings.frontend_origin.rstrip('/')}/#accept-invitation/{token}"},
            dedupe_key=f"workspace-invitation:{invitation.id}",
        )
        db.commit()
    except (ValueError, IntegrityError):
        db.rollback()
        raise InvitationUnavailable from None
    return invitation


def list_workspace_invitations(db: Session, workspace_id: UUID) -> list[tuple[WorkspaceInvitation, str]]:
    now = datetime.now(timezone.utc)
    rows = db.scalars(select(WorkspaceInvitation).where(WorkspaceInvitation.workspace_id == workspace_id).order_by(WorkspaceInvitation.created_at.desc()))
    result = []
    for row in rows:
        expiry = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
        status = "accepted" if row.accepted_at else "revoked" if row.revoked_at else "expired" if expiry <= now else "pending"
        result.append((row, status))
    return result


def revoke_workspace_invitation(db: Session, workspace_id: UUID, invitation_id: UUID) -> bool:
    now = datetime.now(timezone.utc)
    row = db.scalar(select(WorkspaceInvitation).where(
        WorkspaceInvitation.id == invitation_id, WorkspaceInvitation.workspace_id == workspace_id,
    ).with_for_update())
    if row is None:
        return False
    if row.accepted_at is None and row.revoked_at is None:
        row.revoked_at = now
        db.commit()
    return True


def get_invitation_info(db: Session, token: str) -> tuple[WorkspaceInvitation, Workspace]:
    digest = sha256(token.encode("utf-8")).hexdigest()
    row = db.scalar(select(WorkspaceInvitation).where(WorkspaceInvitation.token_hash == digest))
    now = datetime.now(timezone.utc)
    if row is None or row.accepted_at or row.revoked_at or (row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)) <= now:
        raise InvalidInvitation
    workspace = db.get(Workspace, row.workspace_id)
    if workspace is None:
        raise InvalidInvitation
    return row, workspace


def accept_workspace_invitation(db: Session, token: str, password: str):
    invitation, workspace = get_invitation_info(db, token)
    row = db.scalar(select(WorkspaceInvitation).where(WorkspaceInvitation.id == invitation.id).with_for_update())
    now = datetime.now(timezone.utc)
    expiry = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
    if row.accepted_at or row.revoked_at or expiry <= now:
        raise InvalidInvitation
    user = db.scalar(select(User).where(User.email == row.email).with_for_update())
    if user is None:
        user = User(email=row.email, password_hash=hash_password(password), email_verified_at=datetime.now(timezone.utc))
        db.add(user)
        db.flush()
    elif not verify_password(password, user.password_hash):
        raise InvalidCredentials
    existing = db.scalar(select(WorkspaceMembership).where(
        WorkspaceMembership.workspace_id == row.workspace_id, WorkspaceMembership.user_id == user.id,
    ))
    if existing:
        raise InvalidInvitation
    user.email_verified_at = user.email_verified_at or now
    db.add(WorkspaceMembership(workspace_id=row.workspace_id, user_id=user.id, role=row.role))
    row.accepted_at = now
    auth_session, raw_session, raw_csrf = _new_session(user.id)
    db.add(auth_session)
    db.commit()
    return user, workspace, raw_session, raw_csrf
