import base64
from datetime import datetime, timezone
from hashlib import sha256
import secrets
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.events.models import Event, EventStatus, EventVisibility
from app.modules.identity.models import User, WorkspaceMembership
from app.modules.meetings.models import (
    Meeting, MeetingActionHistory, MeetingActionItem, MeetingAgendaItem, MeetingAttachment, MeetingInvitee,
    MeetingDecision, MeetingGuestRegistration, MeetingMinutesRevision,
)
from app.modules.notifications.service import enqueue_notification


class MeetingNotFound(Exception):
    pass


class MeetingConflict(Exception):
    pass


def _meeting(db: Session, workspace_id: UUID, meeting_id: UUID, *, lock: bool = False) -> Meeting:
    query = select(Meeting).where(Meeting.workspace_id == workspace_id, Meeting.id == meeting_id)
    if lock:
        query = query.with_for_update()
    meeting = db.scalar(query)
    if meeting is None:
        raise MeetingNotFound
    return meeting


def _member(db: Session, workspace_id: UUID, user_id: UUID | None) -> bool:
    return user_id is None or db.scalar(select(WorkspaceMembership.id).where(
        WorkspaceMembership.workspace_id == workspace_id,
        WorkspaceMembership.user_id == user_id,
    )) is not None


def create_meeting(db: Session, workspace_id: UUID, created_by_id: UUID, data: dict) -> Meeting:
    event = db.scalar(select(Event).where(
        Event.id == data["event_id"], Event.workspace_id == workspace_id,
    ).with_for_update())
    if event is None:
        raise MeetingNotFound
    if event.visibility != EventVisibility.PRIVATE:
        raise MeetingConflict("Meeting governance is only available for private workspace events")
    if not _member(db, workspace_id, data.get("chairperson_id")):
        raise MeetingConflict("Chairperson must be a member of this workspace")
    meeting = Meeting(workspace_id=workspace_id, created_by_id=created_by_id, **data)
    db.add(meeting)
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        if "uq_meeting_event" in str(exc) or "meetings.event_id" in str(exc):
            raise MeetingConflict("This event already has a meeting record") from None
        raise
    db.refresh(meeting)
    return meeting


def create_scheduled_meeting(db: Session, workspace_id: UUID, created_by_id: UUID, data: dict) -> Meeting:
    """Create the private event and scheduled meeting together to avoid orphan records."""
    event = Event(
        workspace_id=workspace_id,
        created_by_id=created_by_id,
        title=data["title"],
        description=data.get("description"),
        category="meeting",
        status=EventStatus.DRAFT,
        visibility=EventVisibility.PRIVATE,
        start_at=data["start_at"],
        end_at=data["end_at"],
        timezone=data["timezone"],
    )
    try:
        db.add(event)
        db.flush()
        meeting = Meeting(
            workspace_id=workspace_id,
            event_id=event.id,
            meeting_type=data["meeting_type"],
            meeting_mode=data["meeting_mode"],
            online_url=data.get("online_url"),
            status="scheduled",
            created_by_id=created_by_id,
        )
        db.add(meeting)
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(meeting)
    return meeting


def get_meeting(db: Session, workspace_id: UUID, meeting_id: UUID) -> Meeting:
    return _meeting(db, workspace_id, meeting_id)


def list_meetings(db: Session, workspace_id: UUID):
    return list(db.scalars(select(Meeting).where(
        Meeting.workspace_id == workspace_id,
    ).order_by(Meeting.created_at.desc())))


def transition_meeting(db: Session, workspace_id: UUID, meeting_id: UUID, status: str, note: str | None):
    meeting = _meeting(db, workspace_id, meeting_id, lock=True)
    allowed = {"draft": {"scheduled", "cancelled"}, "scheduled": {"held", "cancelled"}}
    if status not in allowed.get(meeting.status, set()):
        raise MeetingConflict(f"Meeting cannot move from {meeting.status} to {status}")
    if status == "cancelled" and not (note and note.strip()):
        raise MeetingConflict("A reason is required to cancel a meeting")
    meeting.status = status
    meeting.cancellation_reason = note.strip() if status == "cancelled" and note else None
    if status in {"held", "cancelled"}:
        meeting.join_token_hash = None
    db.commit()
    db.refresh(meeting)
    return meeting


def add_agenda_item(db: Session, workspace_id: UUID, meeting_id: UUID, actor_id: UUID, data: dict):
    meeting = _meeting(db, workspace_id, meeting_id, lock=True)
    if meeting.status in {"held", "cancelled"}:
        raise MeetingConflict("Agenda cannot be changed after a meeting is held or cancelled")
    if not _member(db, workspace_id, data.get("presenter_id")):
        raise MeetingConflict("Presenter must be a member of this workspace")
    position = db.scalar(select(func.coalesce(func.max(MeetingAgendaItem.position), 0)).where(
        MeetingAgendaItem.meeting_id == meeting.id,
    )) + 1
    item = MeetingAgendaItem(meeting_id=meeting.id, position=position, created_by_id=actor_id, **data)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def list_agenda(db: Session, workspace_id: UUID, meeting_id: UUID):
    meeting = _meeting(db, workspace_id, meeting_id)
    return list(db.scalars(select(MeetingAgendaItem).where(
        MeetingAgendaItem.meeting_id == meeting.id,
    ).order_by(MeetingAgendaItem.position)))


def delete_agenda_item(db: Session, workspace_id: UUID, meeting_id: UUID, item_id: UUID) -> None:
    meeting = _meeting(db, workspace_id, meeting_id, lock=True)
    if meeting.status in {"held", "cancelled"}:
        raise MeetingConflict("Agenda cannot be changed after a meeting is held or cancelled")
    item = db.scalar(select(MeetingAgendaItem).where(
        MeetingAgendaItem.meeting_id == meeting.id, MeetingAgendaItem.id == item_id,
    ).with_for_update())
    if item is None:
        raise MeetingNotFound
    db.delete(item)
    db.flush()
    remaining = list(db.scalars(select(MeetingAgendaItem).where(
        MeetingAgendaItem.meeting_id == meeting.id,
    ).order_by(MeetingAgendaItem.position)))
    for position, current in enumerate(remaining, start=1):
        current.position = position
    db.commit()


def add_invitee(db: Session, workspace_id: UUID, meeting_id: UUID, actor_id: UUID, user_id: UUID):
    meeting = _meeting(db, workspace_id, meeting_id)
    if meeting.status in {"held", "cancelled"}:
        raise MeetingConflict("Invitees cannot be changed after a meeting is held or cancelled")
    if not _member(db, workspace_id, user_id):
        raise MeetingConflict("Invitee must be a member of this workspace")
    if db.scalar(select(MeetingInvitee.id).where(
        MeetingInvitee.meeting_id == meeting.id, MeetingInvitee.user_id == user_id,
    )) is not None:
        raise MeetingConflict("This member is already invited")
    invitee = MeetingInvitee(meeting_id=meeting.id, user_id=user_id, invited_by_id=actor_id)
    db.add(invitee)
    recipient = db.get(User, user_id)
    event = db.get(Event, meeting.event_id)
    enqueue_notification(
        db, workspace_id=workspace_id, kind="meeting_invitation", recipient_email=recipient.email,
        template_key="meeting_invitation",
        context={"full_name": recipient.email.split("@", 1)[0], "meeting_type": meeting.meeting_type,
                 "event_title": event.title, "event_start": event.start_at.isoformat()},
        dedupe_key=f"meeting:{meeting.id}:invitee:{user_id}",
    )
    db.commit()
    db.refresh(invitee)
    return invitee


def list_invitees(db: Session, workspace_id: UUID, meeting_id: UUID):
    meeting = _meeting(db, workspace_id, meeting_id)
    return list(db.scalars(select(MeetingInvitee).where(
        MeetingInvitee.meeting_id == meeting.id,
    ).order_by(MeetingInvitee.invited_at)))


def generate_guest_join_token(db: Session, workspace_id: UUID, meeting_id: UUID) -> str:
    meeting = _meeting(db, workspace_id, meeting_id, lock=True)
    if meeting.status != "scheduled":
        raise MeetingConflict("Schedule the meeting before generating its guest QR link")
    token = secrets.token_urlsafe(32)
    meeting.join_token_hash = sha256(token.encode("ascii")).hexdigest()
    db.commit()
    return token


def revoke_guest_join_token(db: Session, workspace_id: UUID, meeting_id: UUID) -> None:
    meeting = _meeting(db, workspace_id, meeting_id, lock=True)
    meeting.join_token_hash = None
    db.commit()


def _public_join_meeting(db: Session, meeting_id: UUID, token: str, *, lock: bool = False):
    meeting = db.get(Meeting, meeting_id, with_for_update=lock)
    digest = sha256(token.encode("utf-8")).hexdigest()
    if (meeting is None or meeting.status != "scheduled" or not meeting.join_token_hash
            or not secrets.compare_digest(meeting.join_token_hash, digest)):
        raise MeetingNotFound
    event = db.get(Event, meeting.event_id)
    if event is None or getattr(event.status, "value", event.status) == "cancelled":
        raise MeetingNotFound
    if event.end_at:
        event_end = event.end_at if event.end_at.tzinfo else event.end_at.replace(tzinfo=timezone.utc)
        if event_end <= datetime.now(timezone.utc):
            raise MeetingConflict("Registration for this meeting is closed")
    return meeting, event


def get_guest_join_info(db: Session, meeting_id: UUID, token: str) -> dict:
    meeting, event = _public_join_meeting(db, meeting_id, token)
    return {"meeting_id": meeting.id, "meeting_type": meeting.meeting_type,
            "event_title": event.title, "starts_at": event.start_at, "timezone": event.timezone,
            "meeting_mode": meeting.meeting_mode}


def register_meeting_guest(db: Session, meeting_id: UUID, data: dict):
    token = data.pop("token")
    meeting, _event = _public_join_meeting(db, meeting_id, token, lock=True)
    email = str(data["email"]).strip().casefold()
    invited = db.scalar(select(MeetingInvitee.id).join(User, User.id == MeetingInvitee.user_id).where(
        MeetingInvitee.meeting_id == meeting.id, func.lower(User.email) == email,
    ))
    if invited is not None:
        raise MeetingConflict("This email is already on the meeting invite list")
    existing = db.scalar(select(MeetingGuestRegistration).where(
        MeetingGuestRegistration.meeting_id == meeting.id, MeetingGuestRegistration.email == email,
    ))
    join_url = meeting.online_url if meeting.meeting_mode == "online" else None
    if existing is not None:
        return existing, False, join_url
    signature_data = data.pop("signature_data")
    signature_png = base64.b64decode(signature_data.split(",", 1)[1], validate=True)
    guest_data = {key: value for key, value in data.items() if key not in {"email", "token"}}
    guest_data["signature_png"] = signature_png
    guest_data["registration_source"] = "qr"
    guest = MeetingGuestRegistration(meeting_id=meeting.id, email=email, **guest_data)
    db.add(guest)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        guest = db.scalar(select(MeetingGuestRegistration).where(
            MeetingGuestRegistration.meeting_id == meeting.id,
            MeetingGuestRegistration.email == email,
        ))
        if guest is None:
            raise
        return guest, False, join_url
    db.refresh(guest)
    return guest, True, join_url


def add_manual_meeting_guest(db: Session, workspace_id: UUID, meeting_id: UUID, actor_id: UUID, data: dict):
    meeting = _meeting(db, workspace_id, meeting_id, lock=True)
    if meeting.status != "scheduled":
        raise MeetingConflict("Organizer-added attendees can only be added while the meeting is scheduled")
    email = str(data.pop("email")).strip().casefold()
    invitee = db.scalar(select(MeetingInvitee.id).join(User, User.id == MeetingInvitee.user_id).where(
        MeetingInvitee.meeting_id == meeting.id, func.lower(User.email) == email,
    ))
    if invitee is not None:
        raise MeetingConflict("This email is already on the meeting invite list")
    existing = db.scalar(select(MeetingGuestRegistration.id).where(
        MeetingGuestRegistration.meeting_id == meeting.id, MeetingGuestRegistration.email == email,
    ))
    if existing is not None:
        raise MeetingConflict("This email is already registered for the meeting")
    guest = MeetingGuestRegistration(
        meeting_id=meeting.id, email=email, registration_source="admin", registered_by_id=actor_id, **data,
    )
    db.add(guest)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise MeetingConflict("This email is already registered for the meeting") from None
    db.refresh(guest)
    return guest


def list_guest_registrations(db: Session, workspace_id: UUID, meeting_id: UUID):
    meeting = _meeting(db, workspace_id, meeting_id)
    return list(db.scalars(select(MeetingGuestRegistration).where(
        MeetingGuestRegistration.meeting_id == meeting.id,
    ).order_by(MeetingGuestRegistration.registered_at)))


def get_guest_signature(db: Session, workspace_id: UUID, meeting_id: UUID, guest_id: UUID) -> bytes:
    meeting = _meeting(db, workspace_id, meeting_id)
    guest = db.scalar(select(MeetingGuestRegistration).where(
        MeetingGuestRegistration.meeting_id == meeting.id,
        MeetingGuestRegistration.id == guest_id,
    ))
    if guest is None or guest.signature_png is None:
        raise MeetingNotFound
    return guest.signature_png


def erase_guest_privacy_data(db: Session, workspace_id: UUID, meeting_id: UUID, guest_id: UUID):
    meeting = _meeting(db, workspace_id, meeting_id)
    guest = db.scalar(select(MeetingGuestRegistration).where(
        MeetingGuestRegistration.meeting_id == meeting.id,
        MeetingGuestRegistration.id == guest_id,
    ).with_for_update())
    if guest is None:
        raise MeetingNotFound
    guest.signature_png = None
    guest.gps_latitude = None
    guest.gps_longitude = None
    guest.gps_accuracy_m = None
    guest.gps_captured_at = None
    db.commit()
    db.refresh(guest)
    return guest


def record_guest_attendance(db: Session, workspace_id: UUID, meeting_id: UUID, guest_id: UUID,
                            actor_id: UUID, status: str, note: str | None):
    meeting = _meeting(db, workspace_id, meeting_id)
    if meeting.status != "held":
        raise MeetingConflict("Attendance can only be recorded after the meeting is held")
    guest = db.scalar(select(MeetingGuestRegistration).where(
        MeetingGuestRegistration.meeting_id == meeting.id,
        MeetingGuestRegistration.id == guest_id,
    ).with_for_update())
    if guest is None:
        raise MeetingNotFound
    guest.attendance_status = status
    guest.attendance_note = note.strip() if note else None
    guest.recorded_by_id = actor_id
    guest.recorded_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(guest)
    return guest


def remove_invitee(db: Session, workspace_id: UUID, meeting_id: UUID, invitee_id: UUID):
    meeting = _meeting(db, workspace_id, meeting_id)
    if meeting.status in {"held", "cancelled"}:
        raise MeetingConflict("Invitees cannot be changed after a meeting is held or cancelled")
    invitee = db.scalar(select(MeetingInvitee).where(
        MeetingInvitee.meeting_id == meeting.id, MeetingInvitee.id == invitee_id,
    ).with_for_update())
    if invitee is None:
        raise MeetingNotFound
    db.delete(invitee)
    db.commit()


def record_attendance(db: Session, workspace_id: UUID, meeting_id: UUID, invitee_id: UUID,
                      actor_id: UUID, status: str, note: str | None):
    meeting = _meeting(db, workspace_id, meeting_id)
    if meeting.status != "held":
        raise MeetingConflict("Attendance can only be recorded after the meeting is held")
    invitee = db.scalar(select(MeetingInvitee).where(
        MeetingInvitee.meeting_id == meeting.id, MeetingInvitee.id == invitee_id,
    ).with_for_update())
    if invitee is None:
        raise MeetingNotFound
    invitee.attendance_status = status
    invitee.attendance_note = note.strip() if note else None
    invitee.recorded_by_id = actor_id
    invitee.recorded_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(invitee)
    return invitee


def add_attachment(db: Session, workspace_id: UUID, meeting_id: UUID, actor_id: UUID,
                   filename: str, media_type: str, content: bytes):
    meeting = _meeting(db, workspace_id, meeting_id)
    safe_name = filename.replace("\\", "/").split("/")[-1].strip().replace("\r", "").replace("\n", "")[:255]
    if not safe_name or not content:
        raise MeetingConflict("Attachment must have a filename and non-empty content")
    row = MeetingAttachment(
        meeting_id=meeting.id, filename=safe_name, media_type=media_type,
        size_bytes=len(content), content_sha256=sha256(content).hexdigest(),
        content=content, uploaded_by_id=actor_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_attachments(db: Session, workspace_id: UUID, meeting_id: UUID):
    meeting = _meeting(db, workspace_id, meeting_id)
    return list(db.scalars(select(MeetingAttachment).where(
        MeetingAttachment.meeting_id == meeting.id,
    ).order_by(MeetingAttachment.created_at.desc())))


def get_attachment(db: Session, workspace_id: UUID, meeting_id: UUID, attachment_id: UUID):
    meeting = _meeting(db, workspace_id, meeting_id)
    attachment = db.scalar(select(MeetingAttachment).where(
        MeetingAttachment.meeting_id == meeting.id, MeetingAttachment.id == attachment_id,
    ))
    if attachment is None:
        raise MeetingNotFound
    return attachment


def delete_attachment(db: Session, workspace_id: UUID, meeting_id: UUID, attachment_id: UUID):
    attachment = get_attachment(db, workspace_id, meeting_id, attachment_id)
    db.delete(attachment)
    db.commit()


def create_minutes_revision(db: Session, workspace_id: UUID, meeting_id: UUID, actor_id: UUID, content: str):
    meeting = _meeting(db, workspace_id, meeting_id)
    latest = db.scalar(select(func.max(MeetingMinutesRevision.revision)).where(
        MeetingMinutesRevision.meeting_id == meeting.id,
    )) or 0
    row = MeetingMinutesRevision(
        meeting_id=meeting.id, revision=latest + 1, content=content,
        status="draft", created_by_id=actor_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_minutes(db: Session, workspace_id: UUID, meeting_id: UUID):
    meeting = _meeting(db, workspace_id, meeting_id)
    return list(db.scalars(select(MeetingMinutesRevision).where(
        MeetingMinutesRevision.meeting_id == meeting.id,
    ).order_by(MeetingMinutesRevision.revision.desc())))


def _minutes_revision(db: Session, workspace_id: UUID, meeting_id: UUID, revision_id: UUID, lock=False):
    meeting = _meeting(db, workspace_id, meeting_id)
    query = select(MeetingMinutesRevision).where(
        MeetingMinutesRevision.meeting_id == meeting.id,
        MeetingMinutesRevision.id == revision_id,
    )
    if lock:
        query = query.with_for_update()
    row = db.scalar(query)
    if row is None:
        raise MeetingNotFound
    return row


def edit_minutes(db: Session, workspace_id: UUID, meeting_id: UUID, revision_id: UUID, content: str):
    row = _minutes_revision(db, workspace_id, meeting_id, revision_id, lock=True)
    if row.status not in {"draft", "rejected"}:
        raise MeetingConflict("Submitted or approved minutes are immutable; create a new revision")
    row.content = content
    row.status = "draft"
    row.submitted_at = None
    row.approved_by_id = None
    row.approved_at = None
    row.approval_note = None
    db.commit()
    db.refresh(row)
    return row


def submit_minutes(db: Session, workspace_id: UUID, meeting_id: UUID, revision_id: UUID):
    row = _minutes_revision(db, workspace_id, meeting_id, revision_id, lock=True)
    if row.status != "draft":
        raise MeetingConflict("Only draft minutes can be submitted for approval")
    row.status = "submitted"
    row.submitted_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return row


def decide_minutes(
    db: Session, workspace_id: UUID, meeting_id: UUID, revision_id: UUID,
    actor_id: UUID, *, approve: bool, note: str | None,
):
    row = _minutes_revision(db, workspace_id, meeting_id, revision_id, lock=True)
    if row.status != "submitted":
        raise MeetingConflict("Only submitted minutes can be approved or rejected")
    row.status = "approved" if approve else "rejected"
    row.approved_by_id = actor_id
    row.approved_at = datetime.now(timezone.utc)
    row.approval_note = note.strip() if note else None
    db.commit()
    db.refresh(row)
    return row


def create_decision(db: Session, workspace_id: UUID, meeting_id: UUID, actor_id: UUID, data: dict):
    meeting = _meeting(db, workspace_id, meeting_id)
    number = (db.scalar(select(func.max(MeetingDecision.decision_number)).where(
        MeetingDecision.meeting_id == meeting.id,
    )) or 0) + 1
    decision = MeetingDecision(
        meeting_id=meeting.id, decision_number=number,
        proposed_by_id=actor_id, status="proposed", **data,
    )
    db.add(decision)
    db.commit()
    db.refresh(decision)
    return decision


def list_decisions(db: Session, workspace_id: UUID, meeting_id: UUID):
    meeting = _meeting(db, workspace_id, meeting_id)
    return list(db.scalars(select(MeetingDecision).where(
        MeetingDecision.meeting_id == meeting.id,
    ).order_by(MeetingDecision.decision_number)))


def resolve_decision(db: Session, workspace_id: UUID, meeting_id: UUID, decision_id: UUID,
                     actor_id: UUID, result: str, note: str | None):
    meeting = _meeting(db, workspace_id, meeting_id)
    decision = db.scalar(select(MeetingDecision).where(
        MeetingDecision.meeting_id == meeting.id, MeetingDecision.id == decision_id,
    ).with_for_update())
    if decision is None:
        raise MeetingNotFound
    if decision.status != "proposed":
        raise MeetingConflict("A resolved decision cannot be changed")
    decision.status = result
    decision.resolved_by_id = actor_id
    decision.resolved_at = datetime.now(timezone.utc)
    decision.resolution_note = note.strip() if note else None
    db.commit()
    db.refresh(decision)
    return decision


def create_action_item(db: Session, workspace_id: UUID, meeting_id: UUID, actor_id: UUID, data: dict):
    meeting = _meeting(db, workspace_id, meeting_id)
    if not _member(db, workspace_id, data.get("assigned_to_id")):
        raise MeetingConflict("Assignee must be a member of this workspace")
    decision_id = data.get("decision_id")
    if decision_id is not None and db.scalar(select(MeetingDecision.id).where(
        MeetingDecision.id == decision_id, MeetingDecision.meeting_id == meeting.id,
    )) is None:
        raise MeetingNotFound
    item = MeetingActionItem(meeting_id=meeting.id, created_by_id=actor_id, status="open", **data)
    db.add(item)
    db.flush()
    db.add(MeetingActionHistory(
        action_item_id=item.id, from_status=None, to_status="open", changed_by_id=actor_id,
    ))
    db.commit()
    db.refresh(item)
    return item


def list_action_items(db: Session, workspace_id: UUID, meeting_id: UUID):
    meeting = _meeting(db, workspace_id, meeting_id)
    return list(db.scalars(select(MeetingActionItem).where(
        MeetingActionItem.meeting_id == meeting.id,
    ).order_by(MeetingActionItem.due_at, MeetingActionItem.created_at)))


def transition_action_item(db: Session, workspace_id: UUID, meeting_id: UUID, action_id: UUID,
                           actor_id: UUID, status: str, note: str | None):
    meeting = _meeting(db, workspace_id, meeting_id)
    item = db.scalar(select(MeetingActionItem).where(
        MeetingActionItem.meeting_id == meeting.id, MeetingActionItem.id == action_id,
    ).with_for_update())
    if item is None:
        raise MeetingNotFound
    if status == item.status:
        return item
    allowed = {
        "open": {"in_progress", "cancelled"},
        "in_progress": {"open", "completed", "cancelled"},
        "completed": {"in_progress"},
        "cancelled": {"open", "in_progress"},
    }
    if status not in allowed[item.status]:
        raise MeetingConflict(f"Action cannot move from {item.status} to {status}")
    justified = status in {"open", "cancelled"} or item.status in {"completed", "cancelled"}
    if justified and not (note and note.strip()):
        raise MeetingConflict("A note is required to reopen or cancel an action item")
    old_status = item.status
    item.status = status
    item.completed_at = datetime.now(timezone.utc) if status == "completed" else None
    db.add(MeetingActionHistory(
        action_item_id=item.id, from_status=old_status, to_status=status,
        changed_by_id=actor_id, note=note.strip() if note else None,
    ))
    db.commit()
    db.refresh(item)
    return item


def list_action_history(db: Session, workspace_id: UUID, meeting_id: UUID, action_id: UUID):
    meeting = _meeting(db, workspace_id, meeting_id)
    if db.scalar(select(MeetingActionItem.id).where(
        MeetingActionItem.id == action_id, MeetingActionItem.meeting_id == meeting.id,
    )) is None:
        raise MeetingNotFound
    return list(db.scalars(select(MeetingActionHistory).where(
        MeetingActionHistory.action_item_id == action_id,
    ).order_by(MeetingActionHistory.changed_at, MeetingActionHistory.id)))
