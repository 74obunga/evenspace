from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import smtplib
import ssl
from uuid import UUID
import json

from cryptography.fernet import Fernet, InvalidToken

from sqlalchemy import case, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.notifications.models import Notification, NotificationAttempt, NotificationTemplate

MAX_ATTEMPTS = 5
TEMPLATE_VARIABLES = {
    "registration_confirmation": {"full_name", "event_title", "event_start"},
    "meeting_invitation": {"full_name", "meeting_type", "event_title", "event_start"},
    "payment_confirmation": {"full_name", "event_title", "event_start"},
    "refund_update": {"full_name", "event_title", "refund_status"},
    "event_reminder": {"full_name", "event_title", "event_start"},
    "event_update": {"full_name", "event_title", "change_summary"},
    "event_cancellation": {"full_name", "event_title", "reason"},
    "organizer_alert": {"alert_message", "event_title"},
    "ticket_issuance": {"full_name", "event_title", "event_start", "ticket_credential"},
}


def _fernet() -> Fernet | None:
    key = get_settings().notification_encryption_key
    if not key:
        return None
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        return None


def secret_notifications_ready() -> bool:
    return _fernet() is not None


def enqueue_notification(db: Session, *, workspace_id: UUID, kind: str, recipient_email: str,
                         template_key: str, context: dict[str, str], dedupe_key: str | None = None,
                         send_after: datetime | None = None,
                         secret_context: dict[str, str] | None = None) -> Notification:
    ciphertext = None
    if secret_context is not None:
        fernet = _fernet()
        if fernet is None:
            raise ValueError("Notification encryption is not configured")
        ciphertext = fernet.encrypt(json.dumps(secret_context).encode("utf-8")).decode("ascii")
    if dedupe_key is not None:
        existing = db.scalar(select(Notification).where(Notification.dedupe_key == dedupe_key))
        if existing is not None:
            if existing.status == "cancelled" and send_after is not None:
                existing.status = "pending"
                existing.kind = kind
                existing.recipient_email = recipient_email.strip().casefold()
                existing.template_key = template_key
                existing.template_context = context
                existing.secret_context_ciphertext = ciphertext
                existing.last_error = None
                existing.next_attempt_at = send_after
            return existing
    row = Notification(
        workspace_id=workspace_id, kind=kind, recipient_email=recipient_email.strip().casefold(),
        template_key=template_key, template_context=context,
        secret_context_ciphertext=ciphertext, dedupe_key=dedupe_key,
        next_attempt_at=send_after or datetime.now(timezone.utc),
    )
    db.add(row)
    return row


def _smtp_send(recipient: str, subject: str, body: str) -> None:
    settings = get_settings()
    if not settings.smtp_host:
        raise RuntimeError("Email delivery is not configured (SMTP_HOST is missing)")
    message = EmailMessage()
    message["From"] = settings.smtp_from_email
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as client:
        client.ehlo()
        if settings.smtp_starttls:
            client.starttls(context=ssl.create_default_context())
            client.ehlo()
        if settings.smtp_username:
            client.login(settings.smtp_username, settings.smtp_password or "")
        client.send_message(message)


def deliver_due(db: Session, limit: int = 25) -> int:
    if not get_settings().smtp_host:
        return 0
    now = datetime.now(timezone.utc)
    rows = list(db.scalars(
        select(Notification)
        .where(Notification.status == "pending", Notification.next_attempt_at <= now,
               Notification.attempt_count < MAX_ATTEMPTS * (Notification.retry_generation + 1))
        .order_by(Notification.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ))
    for row in rows:
        template_query = select(NotificationTemplate).where(NotificationTemplate.key == row.template_key)
        if row.kind in {"password_reset", "email_verification", "workspace_invitation"}:
            template_query = template_query.where(NotificationTemplate.workspace_id.is_(None))
        else:
            template_query = template_query.where(or_(
                NotificationTemplate.workspace_id == row.workspace_id,
                NotificationTemplate.workspace_id.is_(None),
            )).order_by(case((NotificationTemplate.workspace_id == row.workspace_id, 0), else_=1))
        template = db.scalar(template_query.limit(1))
        number = row.attempt_count + 1
        error = None
        try:
            if template is None or not template.enabled:
                raise RuntimeError("Notification template is missing or disabled")
            render_context = dict(row.template_context)
            if row.secret_context_ciphertext:
                fernet = _fernet()
                if fernet is None:
                    raise RuntimeError("Notification encryption is not configured")
                try:
                    render_context.update(json.loads(fernet.decrypt(
                        row.secret_context_ciphertext.encode("ascii")).decode("utf-8")))
                except (InvalidToken, ValueError, UnicodeDecodeError, json.JSONDecodeError):
                    raise RuntimeError("Could not decrypt notification content") from None
            subject = template.subject_template.format_map(render_context)
            body = template.body_template.format_map(render_context)
            _smtp_send(row.recipient_email, subject, body)
        except Exception as exc:
            error = str(exc)[:1000] or type(exc).__name__
            row.status = "failed" if number >= MAX_ATTEMPTS * (row.retry_generation + 1) else "pending"
            row.last_error = error
            row.next_attempt_at = now + timedelta(seconds=min(3600, 60 * (2 ** (number - 1))))
            attempt_status = "failed"
        else:
            row.status = "sent"
            row.sent_at = datetime.now(timezone.utc)
            row.last_error = None
            attempt_status = "sent"
        row.attempt_count = number
        db.add(NotificationAttempt(
            notification_id=row.id, attempt_number=number, status=attempt_status, error=error,
        ))
        db.commit()
    return len(rows)


def enqueue_ticket_issuance(db: Session, *, workspace_id: UUID, recipient_email: str,
                            full_name: str, event_title: str, event_start: str,
                            credential: str, dedupe_key: str) -> Notification | None:
    if _fernet() is None:
        return None
    return enqueue_notification(
        db, workspace_id=workspace_id, kind="ticket_issuance", recipient_email=recipient_email,
        template_key="ticket_issuance",
        context={"full_name": full_name, "event_title": event_title, "event_start": event_start},
        secret_context={"ticket_credential": credential}, dedupe_key=dedupe_key,
    )


def list_notifications(db: Session, workspace_id: UUID):
    return list(db.scalars(select(Notification).where(
        Notification.workspace_id == workspace_id,
    ).order_by(Notification.created_at.desc()).limit(200)))


def cancel_pending(db: Session, dedupe_key_prefix: str) -> None:
    rows = db.scalars(select(Notification).where(
        Notification.dedupe_key.like(f"{dedupe_key_prefix}%"), Notification.status == "pending",
    ))
    for row in rows:
        row.status = "cancelled"
        row.last_error = "Cancelled because the event schedule or status changed"


def schedule_event_reminder(db: Session, *, workspace_id: UUID, event, registration) -> None:
    now = datetime.now(timezone.utc)
    start = event.start_at if event.start_at.tzinfo else event.start_at.replace(tzinfo=timezone.utc)
    until_start = start.astimezone(timezone.utc) - now
    if until_start > timedelta(hours=25):
        send_after = start.astimezone(timezone.utc) - timedelta(hours=24)
    elif until_start > timedelta(hours=2):
        send_after = start.astimezone(timezone.utc) - timedelta(hours=1)
    else:
        return
    enqueue_notification(
        db, workspace_id=workspace_id, kind="event_reminder", recipient_email=registration.email,
        template_key="event_reminder",
        context={"full_name": registration.full_name, "event_title": event.title,
                 "event_start": event.start_at.isoformat()},
        dedupe_key=f"event:{event.id}:registration:{registration.id}:reminder:{send_after.isoformat()}",
        send_after=send_after,
    )


def retry_notification(db: Session, workspace_id: UUID, notification_id: UUID):
    row = db.scalar(select(Notification).where(
        Notification.workspace_id == workspace_id, Notification.id == notification_id,
    ).with_for_update())
    if row is None:
        return None
    if row.status != "failed":
        raise ValueError("Only failed notifications can be retried")
    row.status = "pending"
    row.retry_generation += 1
    row.next_attempt_at = datetime.now(timezone.utc)
    row.last_error = None
    db.commit()
    db.refresh(row)
    return row


def list_templates(db: Session, workspace_id: UUID):
    templates = list(db.scalars(select(NotificationTemplate).where(
        or_(NotificationTemplate.workspace_id == workspace_id, NotificationTemplate.workspace_id.is_(None)),
    )))
    effective = {}
    for template in templates:
        if template.key not in effective or template.workspace_id == workspace_id:
            effective[template.key] = template
    return sorted(effective.values(), key=lambda row: row.key)


def update_template(db: Session, workspace_id: UUID, actor_id: UUID, key: str,
                    subject_template: str, body_template: str, enabled: bool):
    if key in {"password_reset", "email_verification", "workspace_invitation"}:
        raise ValueError("Security account email templates cannot be customized")
    if key not in TEMPLATE_VARIABLES:
        raise ValueError("Unknown notification template")
    from string import Formatter
    try:
        used = {field for _, field, _, _ in Formatter().parse(subject_template + body_template) if field}
    except ValueError:
        raise ValueError("Template has invalid formatting braces") from None
    if not used.issubset(TEMPLATE_VARIABLES[key]):
        raise ValueError("Template contains an unsupported variable")
    template = db.scalar(select(NotificationTemplate).where(
        NotificationTemplate.workspace_id == workspace_id, NotificationTemplate.key == key,
    ).with_for_update())
    if template is None:
        defaults = db.scalar(select(NotificationTemplate).where(
            NotificationTemplate.workspace_id.is_(None), NotificationTemplate.key == key,
        ))
        if defaults is None:
            raise ValueError("Default notification template is missing")
        template = NotificationTemplate(
            workspace_id=workspace_id, key=key, channel=defaults.channel,
            subject_template=subject_template, body_template=body_template,
            enabled=enabled, updated_by_id=actor_id,
        )
        db.add(template)
    else:
        template.subject_template = subject_template
        template.body_template = body_template
        template.enabled = enabled
        template.updated_by_id = actor_id
    db.commit()
    db.refresh(template)
    return template
