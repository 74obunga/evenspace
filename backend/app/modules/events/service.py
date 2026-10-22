from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.modules.events.models import (
    AttendanceEvent,
    AttendanceEventType,
    Event,
    EventOperatorAssignment,
    EventStatus,
    EventVisibility,
    OfflineConflictStatus,
    OfflineScanConflict,
    Registration,
    RegistrationStatus,
    Ticket,
    TicketStatus,
    TicketType,
    ScanDevice,
    ScanDeviceSnapshot,
    ScanDeviceSnapshotTicket,
    SyncBatch,
)
from app.modules.identity.models import User, WorkspaceMembership, WorkspaceRole
from app.modules.notifications.service import (
    cancel_pending, enqueue_notification, enqueue_ticket_issuance, schedule_event_reminder,
)


class EventNotFound(Exception):
    pass


class EventConflict(Exception):
    pass


class TicketTypeNotFound(Exception):
    pass


class CapacityReached(Exception):
    pass


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def create_event(db: Session, workspace_id: UUID, created_by_id: UUID, data: dict) -> Event:
    data["visibility"] = EventVisibility(data["visibility"])
    event = Event(workspace_id=workspace_id, created_by_id=created_by_id, **data)
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def list_workspace_events(db: Session, workspace_id: UUID) -> list[Event]:
    return list(db.scalars(
        select(Event)
        .options(selectinload(Event.ticket_types))
        .where(Event.workspace_id == workspace_id)
        .order_by(Event.start_at.desc())
    ))


def get_workspace_event(db: Session, workspace_id: UUID, event_id: UUID) -> Event:
    event = db.scalar(
        select(Event)
        .options(selectinload(Event.ticket_types))
        .where(Event.id == event_id, Event.workspace_id == workspace_id)
    )
    if event is None:
        raise EventNotFound
    return event


def update_workspace_event(db: Session, workspace_id: UUID, event_id: UUID, data: dict) -> Event:
    event = db.scalar(select(Event).where(
        Event.id == event_id, Event.workspace_id == workspace_id,
    ).with_for_update())
    if event is None:
        raise EventNotFound
    if event.status not in {EventStatus.DRAFT, EventStatus.PUBLISHED}:
        raise EventConflict("Only draft or published events can be edited")
    merged = {
        "title": event.title, "description": event.description, "category": event.category,
        "start_at": data.get("start_at", event.start_at), "end_at": data.get("end_at", event.end_at),
        "timezone": data.get("timezone", event.timezone),
    }
    if merged["end_at"] <= merged["start_at"]:
        raise EventConflict("Event end must be after its start")
    if event.registration_close_at and event.registration_close_at > merged["start_at"]:
        raise EventConflict("Registration must close by the event start")
    if event.registration_open_at and event.registration_open_at >= merged["start_at"]:
        raise EventConflict("Registration must open before the event starts")
    changes = {key: (getattr(event, key), value) for key, value in data.items()
               if getattr(event, key) != value}
    if not changes:
        return event
    for key, value in data.items():
        setattr(event, key, value)
    if event.status == EventStatus.PUBLISHED and event.registration_count:
        registrations = list(db.scalars(select(Registration).where(
            Registration.event_id == event.id, Registration.status == RegistrationStatus.CONFIRMED,
        )))
        summary = "; ".join(f"{key.replace('_', ' ')} updated" for key in changes)
        change_digest = hashlib.sha256(repr(sorted((key, str(new)) for key, (_, new) in changes.items())).encode()).hexdigest()[:20]
        update_batch = uuid4()
        for registration in registrations:
            if "start_at" in changes or "title" in changes:
                cancel_pending(db, f"event:{event.id}:registration:{registration.id}:reminder")
                schedule_event_reminder(db, workspace_id=workspace_id, event=event, registration=registration)
            enqueue_notification(
                db, workspace_id=workspace_id, kind="event_update", recipient_email=registration.email,
                template_key="event_update",
                context={"full_name": registration.full_name, "event_title": event.title,
                         "change_summary": summary},
                dedupe_key=f"event:{event.id}:registration:{registration.id}:update:{update_batch}:{change_digest}",
            )
    db.commit()
    db.refresh(event)
    return event


def cancel_workspace_event(db: Session, workspace_id: UUID, event_id: UUID, reason: str) -> Event:
    event = db.scalar(select(Event).where(
        Event.id == event_id, Event.workspace_id == workspace_id,
    ).with_for_update())
    if event is None:
        raise EventNotFound
    if event.status not in {EventStatus.DRAFT, EventStatus.PUBLISHED}:
        raise EventConflict("Only draft or published events can be cancelled")
    pending = db.scalar(select(Registration.id).where(
        Registration.event_id == event.id, Registration.status == RegistrationStatus.PENDING_PAYMENT,
    ).limit(1))
    if pending is not None:
        raise EventConflict("Resolve pending payments before cancelling this event")
    event.status = EventStatus.CANCELLED
    registrations = list(db.scalars(select(Registration).where(
        Registration.event_id == event.id, Registration.status == RegistrationStatus.CONFIRMED,
    )))
    for registration in registrations:
        cancel_pending(db, f"event:{event.id}:registration:{registration.id}:reminder")
        enqueue_notification(
            db, workspace_id=workspace_id, kind="event_cancellation", recipient_email=registration.email,
            template_key="event_cancellation",
            context={"full_name": registration.full_name, "event_title": event.title, "reason": reason},
            dedupe_key=f"event:{event.id}:registration:{registration.id}:cancelled",
        )
    db.commit()
    db.refresh(event)
    return event


def add_free_ticket_type(db: Session, workspace_id: UUID, event_id: UUID, data: dict) -> TicketType:
    event = db.scalar(
        select(Event).where(Event.id == event_id, Event.workspace_id == workspace_id).with_for_update()
    )
    if event is None:
        raise EventNotFound
    if event.status != EventStatus.DRAFT:
        raise EventConflict("Ticket types can only be changed while an event is a draft")
    if data.get("capacity") is not None and event.capacity is not None and data["capacity"] > event.capacity:
        raise EventConflict("Ticket type capacity cannot exceed event capacity")
    ticket_type = TicketType(event_id=event.id, **data)
    db.add(ticket_type)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise EventConflict("Ticket type names must be unique within an event") from None
    db.refresh(ticket_type)
    return ticket_type


def publish_event(db: Session, workspace_id: UUID, event_id: UUID) -> Event:
    event = db.scalar(
        select(Event).where(Event.id == event_id, Event.workspace_id == workspace_id).with_for_update()
    )
    if event is None:
        raise EventNotFound
    if event.status != EventStatus.DRAFT:
        raise EventConflict("Only draft events can be published")
    ticket_type_count = db.query(TicketType.id).filter(
        TicketType.event_id == event.id, TicketType.is_active.is_(True)
    ).count()
    if ticket_type_count == 0:
        raise EventConflict("Add at least one active ticket type before publishing")
    event.status = EventStatus.PUBLISHED
    db.commit()
    db.refresh(event)
    return event


def get_public_event(db: Session, event_id: UUID) -> Event:
    event = db.scalar(
        select(Event)
        .options(selectinload(Event.ticket_types))
        .where(
            Event.id == event_id,
            Event.status == EventStatus.PUBLISHED,
            Event.visibility == EventVisibility.PUBLIC,
        )
    )
    if event is None:
        raise EventNotFound
    return event


def list_public_events(db: Session, limit: int = 50) -> list[Event]:
    now = datetime.now(timezone.utc)
    events = db.scalars(
        select(Event)
        .options(selectinload(Event.ticket_types))
        .where(
            Event.status == EventStatus.PUBLISHED,
            Event.visibility == EventVisibility.PUBLIC,
            Event.start_at > now,
            (Event.registration_close_at.is_(None) | (Event.registration_close_at > now)),
            (Event.capacity.is_(None) | (Event.registration_count < Event.capacity)),
        )
        .order_by(Event.start_at.asc())
        .limit(limit)
    )
    return [
        event for event in events
        if any(item.is_active and (item.capacity is None or item.registration_count < item.capacity)
               for item in event.ticket_types)
    ]


def register_participant(
    db: Session, event_id: UUID, ticket_type_id: UUID, full_name: str, email: str, idempotency_key: str
) -> tuple[Registration, Ticket, bool, str]:
    event = db.scalar(select(Event).where(Event.id == event_id).with_for_update())
    if (event is None or event.status != EventStatus.PUBLISHED
            or event.visibility != EventVisibility.PUBLIC):
        raise EventNotFound

    normalized_email = email.strip().casefold()
    key_hash = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    existing = db.scalar(select(Registration).where(
        Registration.event_id == event.id, Registration.email == normalized_email
    ))
    if existing is not None:
        ticket = db.scalar(select(Ticket).where(Ticket.registration_id == existing.id))
        if existing.idempotency_key_hash == key_hash and ticket is not None:
            credential = _ticket_credential(idempotency_key, ticket.id)
            if ticket.status == TicketStatus.ACTIVE and ticket.credential_hash == _credential_hash(credential):
                return existing, ticket, False, credential
        raise EventConflict("This email is already registered for the event")
    key_owner = db.scalar(select(Registration).where(
        Registration.event_id == event.id, Registration.idempotency_key_hash == key_hash
    ))
    if key_owner is not None:
        raise EventConflict("This idempotency key was already used for another registration")

    now = datetime.now(timezone.utc)
    if event.registration_open_at and now < _utc(event.registration_open_at):
        raise EventConflict("Registration has not opened")
    if (event.registration_close_at and now >= _utc(event.registration_close_at)) or now >= _utc(event.start_at):
        raise EventConflict("Registration is closed")

    ticket_type = db.scalar(select(TicketType).where(
        TicketType.id == ticket_type_id,
        TicketType.event_id == event.id,
        TicketType.is_active.is_(True),
    ).with_for_update())
    if ticket_type is None:
        raise TicketTypeNotFound
    if ticket_type.price > 0:
        # Never let the free-registration endpoint issue a ticket for a priced type.
        raise EventConflict("Paid ticket checkout is not available yet")

    event_reservation = db.execute(
        update(Event)
        .where(
            Event.id == event.id,
            Event.status == EventStatus.PUBLISHED,
            or_(Event.capacity.is_(None), Event.registration_count < Event.capacity),
        )
        .values(registration_count=Event.registration_count + 1)
    )
    if event_reservation.rowcount != 1:
        raise CapacityReached("This event is full")

    ticket_reservation = db.execute(
        update(TicketType)
        .where(
            TicketType.id == ticket_type.id,
            TicketType.is_active.is_(True),
            or_(TicketType.capacity.is_(None), TicketType.registration_count < TicketType.capacity),
        )
        .values(registration_count=TicketType.registration_count + 1)
    )
    if ticket_reservation.rowcount != 1:
        raise CapacityReached("This ticket type is full")

    registration = Registration(
        event_id=event.id,
        ticket_type_id=ticket_type.id,
        full_name=full_name.strip(),
        email=normalized_email,
        idempotency_key_hash=key_hash,
        status=RegistrationStatus.CONFIRMED,
        confirmation_code=secrets.token_urlsafe(18),
    )
    db.add(registration)
    try:
        db.flush()
        ticket_id = uuid4()
        credential = _ticket_credential(idempotency_key, ticket_id)
        ticket = Ticket(
            id=ticket_id,
            event_id=event.id,
            registration_id=registration.id,
            ticket_type_id=ticket_type.id,
            credential_hash=_credential_hash(credential),
            status=TicketStatus.ACTIVE,
        )
        db.add(ticket)
        enqueue_ticket_issuance(
            db, workspace_id=event.workspace_id, recipient_email=registration.email,
            full_name=registration.full_name, event_title=event.title,
            event_start=event.start_at.isoformat(), credential=credential,
            dedupe_key=f"registration:{registration.id}:ticket",
        )
        enqueue_notification(
            db, workspace_id=event.workspace_id, kind="registration_confirmation",
            recipient_email=registration.email, template_key="registration_confirmation",
            context={"full_name": registration.full_name, "event_title": event.title,
                     "event_start": event.start_at.isoformat()},
            dedupe_key=f"registration:{registration.id}:confirmation",
        )
        schedule_event_reminder(db, workspace_id=event.workspace_id, event=event, registration=registration)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise EventConflict("This email or idempotency key is already registered") from None
    db.refresh(registration)
    db.refresh(ticket)
    return registration, ticket, True, credential


def _ticket_credential(idempotency_key: str, ticket_id: UUID) -> str:
    material = f"evenspace:ticket:v1:{ticket_id}:{idempotency_key}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _credential_hash(credential: str) -> str:
    return hashlib.sha256(credential.encode("ascii")).hexdigest()


def get_participant_ticket(db: Session, credential: str):
    row = db.execute(
        select(Ticket, Event, Registration, TicketType)
        .join(Event, Event.id == Ticket.event_id)
        .join(Registration, Registration.id == Ticket.registration_id)
        .join(TicketType, TicketType.id == Ticket.ticket_type_id)
        .where(Ticket.credential_hash == _credential_hash(credential), Ticket.status == TicketStatus.ACTIVE)
    ).first()
    return row


def start_event(db: Session, workspace_id: UUID, event_id: UUID) -> Event:
    event = db.scalar(select(Event).where(Event.id == event_id, Event.workspace_id == workspace_id).with_for_update())
    if event is None:
        raise EventNotFound
    if event.status != EventStatus.PUBLISHED:
        raise EventConflict("Only published events can be started")
    event.status = EventStatus.IN_PROGRESS
    db.commit()
    db.refresh(event)
    return event


def revoke_ticket(db: Session, workspace_id: UUID, event_id: UUID, ticket_id: UUID) -> Ticket:
    ticket = db.scalar(
        select(Ticket)
        .join(Event, Event.id == Ticket.event_id)
        .where(Event.workspace_id == workspace_id, Event.id == event_id, Ticket.id == ticket_id)
        .with_for_update()
    )
    if ticket is None:
        raise TicketTypeNotFound
    if ticket.status == TicketStatus.ACTIVE:
        ticket.status = TicketStatus.REVOKED
        ticket.revoked_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(ticket)
    return ticket


def assign_operator(db: Session, workspace_id: UUID, event_id: UUID, user_id: UUID, assigned_by_id: UUID):
    event = db.scalar(select(Event).where(Event.id == event_id, Event.workspace_id == workspace_id))
    if event is None:
        raise EventNotFound
    membership = db.scalar(select(WorkspaceMembership).where(
        WorkspaceMembership.workspace_id == workspace_id,
        WorkspaceMembership.user_id == user_id,
    ))
    if membership is None:
        raise EventConflict("Gate operators must be workspace members")
    assignment = db.scalar(select(EventOperatorAssignment).where(
        EventOperatorAssignment.event_id == event_id,
        EventOperatorAssignment.user_id == user_id,
    ))
    if assignment is not None:
        return assignment
    assignment = EventOperatorAssignment(event_id=event_id, user_id=user_id, assigned_by_id=assigned_by_id)
    db.add(assignment)
    operator = db.get(User, user_id)
    if operator is not None:
        enqueue_notification(
            db, workspace_id=workspace_id, kind="organizer_alert", recipient_email=operator.email,
            template_key="organizer_alert",
            context={"event_title": event.title,
                     "alert_message": f"You have been assigned as a gate operator for {event.title}."},
            dedupe_key=f"event:{event_id}:operator:{user_id}:assigned",
        )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        assignment = db.scalar(select(EventOperatorAssignment).where(
            EventOperatorAssignment.event_id == event_id,
            EventOperatorAssignment.user_id == user_id,
        ))
        if assignment is None:
            raise
    db.refresh(assignment)
    return assignment


def remove_operator(db: Session, workspace_id: UUID, event_id: UUID, user_id: UUID) -> None:
    assignment = db.scalar(
        select(EventOperatorAssignment)
        .join(Event, Event.id == EventOperatorAssignment.event_id)
        .where(Event.workspace_id == workspace_id, Event.id == event_id,
               EventOperatorAssignment.user_id == user_id)
    )
    if assignment is None:
        raise EventNotFound
    db.delete(assignment)
    db.commit()


class AttendanceForbidden(Exception):
    pass


def check_in_ticket(
    db: Session, event_id: UUID, user_id: UUID, credential: str, scan_event_id: UUID
) -> tuple[AttendanceEvent, Ticket, Registration, bool]:
    event = db.scalar(select(Event).where(Event.id == event_id).with_for_update())
    if event is None:
        raise EventNotFound
    if event.status != EventStatus.IN_PROGRESS:
        raise EventConflict("Check-in is available only while the event is in progress")

    manager = db.scalar(select(WorkspaceMembership.id).where(
        WorkspaceMembership.workspace_id == event.workspace_id,
        WorkspaceMembership.user_id == user_id,
        WorkspaceMembership.role.in_([WorkspaceRole.OWNER, WorkspaceRole.ADMIN]),
    ))
    assignment = db.scalar(select(EventOperatorAssignment.id).where(
        EventOperatorAssignment.event_id == event_id,
        EventOperatorAssignment.user_id == user_id,
    ))
    if manager is None and assignment is None:
        raise AttendanceForbidden

    ticket = db.scalar(select(Ticket).where(
        Ticket.event_id == event.id,
        Ticket.credential_hash == _credential_hash(credential),
        Ticket.status == TicketStatus.ACTIVE,
    ).with_for_update())
    if ticket is None:
        raise TicketTypeNotFound

    prior_scan = db.scalar(select(AttendanceEvent).where(AttendanceEvent.scan_event_id == scan_event_id))
    if prior_scan is not None:
        if prior_scan.ticket_id != ticket.id or prior_scan.event_id != event.id:
            raise EventConflict("Scan event identifier was already used for another ticket")
        registration = db.get(Registration, ticket.registration_id)
        return prior_scan, ticket, registration, True

    existing_checkin = db.scalar(select(AttendanceEvent).where(
        AttendanceEvent.event_id == event.id,
        AttendanceEvent.ticket_id == ticket.id,
        AttendanceEvent.event_type == AttendanceEventType.CHECK_IN,
    ))
    if existing_checkin is not None:
        registration = db.get(Registration, ticket.registration_id)
        return existing_checkin, ticket, registration, True

    attendance = AttendanceEvent(
        event_id=event.id,
        ticket_id=ticket.id,
        event_type=AttendanceEventType.CHECK_IN,
        scan_event_id=scan_event_id,
        recorded_by_id=user_id,
    )
    db.add(attendance)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        prior_scan = db.scalar(select(AttendanceEvent).where(AttendanceEvent.scan_event_id == scan_event_id))
        existing_checkin = db.scalar(select(AttendanceEvent).where(
            AttendanceEvent.event_id == event.id,
            AttendanceEvent.ticket_id == ticket.id,
            AttendanceEvent.event_type == AttendanceEventType.CHECK_IN,
        ))
        existing = prior_scan or existing_checkin
        if existing is None or existing.ticket_id != ticket.id or existing.event_id != event.id:
            raise EventConflict("Ticket has already been checked in") from None
        registration = db.get(Registration, ticket.registration_id)
        return existing, ticket, registration, True
    db.refresh(attendance)
    registration = db.get(Registration, ticket.registration_id)
    return attendance, ticket, registration, False


def manual_check_in_registration(
    db: Session, workspace_id: UUID, event_id: UUID, registration_id: UUID, user_id: UUID
) -> tuple[AttendanceEvent, Ticket, Registration, bool]:
    event = db.scalar(select(Event).where(Event.id == event_id, Event.workspace_id == workspace_id).with_for_update())
    if event is None:
        raise EventNotFound
    if event.status != EventStatus.IN_PROGRESS:
        raise EventConflict("Check-in is available only while the event is in progress")

    registration = db.scalar(select(Registration).where(
        Registration.id == registration_id, Registration.event_id == event_id
    ).with_for_update())
    if registration is None:
        raise EventNotFound
    if registration.status != RegistrationStatus.CONFIRMED:
        raise EventConflict("Only confirmed registrations can be checked in")

    ticket = db.scalar(select(Ticket).where(
        Ticket.registration_id == registration.id,
        Ticket.status == TicketStatus.ACTIVE,
    ).with_for_update())
    if ticket is None:
        raise EventConflict("No active ticket found for this registration")

    existing_checkin = db.scalar(select(AttendanceEvent).where(
        AttendanceEvent.event_id == event.id,
        AttendanceEvent.ticket_id == ticket.id,
        AttendanceEvent.event_type == AttendanceEventType.CHECK_IN,
    ))
    if existing_checkin is not None:
        return existing_checkin, ticket, registration, True

    attendance = AttendanceEvent(
        event_id=event.id,
        ticket_id=ticket.id,
        event_type=AttendanceEventType.CHECK_IN,
        scan_event_id=uuid4(),
        recorded_by_id=user_id,
        source="manual",
    )
    db.add(attendance)
    db.commit()
    db.refresh(attendance)
    return attendance, ticket, registration, False


def list_attendance(db: Session, workspace_id: UUID, event_id: UUID, user_id: UUID):
    event = db.scalar(select(Event).where(Event.id == event_id, Event.workspace_id == workspace_id))
    if event is None:
        raise EventNotFound
    manager = db.scalar(select(WorkspaceMembership.id).where(
        WorkspaceMembership.workspace_id == workspace_id,
        WorkspaceMembership.user_id == user_id,
        WorkspaceMembership.role.in_([WorkspaceRole.OWNER, WorkspaceRole.ADMIN, WorkspaceRole.EVENT_MANAGER]),
    ))
    assignment = db.scalar(select(EventOperatorAssignment.id).where(
        EventOperatorAssignment.event_id == event_id,
        EventOperatorAssignment.user_id == user_id,
    ))
    if manager is None and assignment is None:
        raise AttendanceForbidden
    rows = db.execute(
        select(AttendanceEvent, Ticket, Registration)
        .join(Ticket, Ticket.id == AttendanceEvent.ticket_id)
        .join(Registration, Registration.id == Ticket.registration_id)
        .where(AttendanceEvent.event_id == event_id)
        .order_by(AttendanceEvent.scanned_at)
    )
    return list(rows)


def list_event_registrations(db: Session, workspace_id: UUID, event_id: UUID):
    event_exists = db.scalar(select(Event.id).where(
        Event.id == event_id, Event.workspace_id == workspace_id,
    ))
    if event_exists is None:
        raise EventNotFound
    return list(db.execute(
        select(Registration, TicketType.name, Ticket.status, AttendanceEvent.scanned_at)
        .join(TicketType, TicketType.id == Registration.ticket_type_id)
        .outerjoin(Ticket, Ticket.registration_id == Registration.id)
        .outerjoin(AttendanceEvent, and_(
            AttendanceEvent.ticket_id == Ticket.id,
            AttendanceEvent.event_type == AttendanceEventType.CHECK_IN,
        ))
        .where(Registration.event_id == event_id)
        .order_by(Registration.registered_at.desc(), Registration.id)
    ))


def create_scan_device(db: Session, workspace_id: UUID, event_id: UUID, user_id: UUID, name: str, days: int):
    event = db.scalar(select(Event).where(Event.id == event_id, Event.workspace_id == workspace_id))
    if event is None:
        raise EventNotFound
    token = secrets.token_urlsafe(32)
    device = ScanDevice(event_id=event_id, name=name, token_hash=_credential_hash(token),
                        created_by_id=user_id, expires_at=datetime.now(timezone.utc) + timedelta(days=days))
    db.add(device)
    db.commit()
    db.refresh(device)
    return device, token


def list_scan_devices(db: Session, workspace_id: UUID, event_id: UUID) -> list[ScanDevice]:
    event = db.scalar(select(Event).where(Event.id == event_id, Event.workspace_id == workspace_id))
    if event is None:
        raise EventNotFound
    return list(db.scalars(
        select(ScanDevice)
        .where(ScanDevice.event_id == event_id)
        .order_by(ScanDevice.created_at.desc())
    ))


def revoke_scan_device(db: Session, workspace_id: UUID, event_id: UUID, device_id: UUID):
    device = db.scalar(select(ScanDevice).join(Event, Event.id == ScanDevice.event_id).where(
        ScanDevice.id == device_id, ScanDevice.event_id == event_id, Event.workspace_id == workspace_id
    ))
    if device is None:
        raise EventNotFound
    device.revoked_at = datetime.now(timezone.utc)
    db.commit()


def _device_for_token(db: Session, event_id: UUID, token: str) -> ScanDevice:
    device = db.scalar(select(ScanDevice).where(
        ScanDevice.event_id == event_id, ScanDevice.token_hash == _credential_hash(token)
    ))
    now = datetime.now(timezone.utc)
    if device is None or device.revoked_at is not None or _utc(device.expires_at) <= now:
        raise AttendanceForbidden
    return device


def create_offline_manifest(db: Session, event_id: UUID, token: str):
    device = _device_for_token(db, event_id, token)
    event = db.get(Event, event_id)
    if event is None:
        raise EventNotFound
    now = datetime.now(timezone.utc)
    snapshot = ScanDeviceSnapshot(device_id=device.id, generated_at=now)
    db.add(snapshot)
    db.flush()
    rows = db.execute(select(Ticket, Registration).join(
        Registration, Registration.id == Ticket.registration_id
    ).where(Ticket.event_id == event_id)).all()
    db.add_all([ScanDeviceSnapshotTicket(snapshot_id=snapshot.id, ticket_id=t.id,
        credential_hash=t.credential_hash, ticket_status=t.status.value, attendee_name=r.full_name)
        for t, r in rows])
    result = {
        "snapshot_id": snapshot.id, "generated_at": now, "event_id": event.id,
        "event_title": event.title, "starts_at": event.start_at,
        "tickets": [{"ticket_id": t.id, "credential_hash": t.credential_hash,
                     "status": t.status.value, "attendee_name": r.full_name} for t, r in rows],
    }
    db.commit()
    return result


def sync_offline_batch(db: Session, event_id: UUID, token: str, payload: dict):
    import json
    device = _device_for_token(db, event_id, token)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    existing_batch = db.scalar(select(SyncBatch).where(
        SyncBatch.device_id == device.id, SyncBatch.batch_id == payload["batch_id"]
    ))
    if existing_batch:
        if existing_batch.request_digest != digest:
            raise EventConflict("Batch identifier was reused with different data")
        return existing_batch.result
    snapshot = db.scalar(select(ScanDeviceSnapshot).where(
        ScanDeviceSnapshot.id == payload["snapshot_id"], ScanDeviceSnapshot.device_id == device.id
    ))
    if snapshot is None:
        raise EventConflict("Snapshot does not belong to this device")
    event = db.get(Event, event_id)
    if event is None:
        raise EventNotFound
    batch = SyncBatch(device_id=device.id, batch_id=payload["batch_id"], snapshot_id=snapshot.id,
                      request_digest=digest, result={})
    db.add(batch)
    db.flush()
    outcomes = []
    for scan in payload["scans"]:
        credential_hash = _credential_hash(scan["credential"])
        ticket = db.scalar(select(Ticket).where(
            Ticket.event_id == event_id, Ticket.credential_hash == credential_hash
        ))
        scanned_at = scan["scanned_at"]
        reason = None
        if ticket is None:
            reason = "unknown_ticket"
        elif db.scalar(select(ScanDeviceSnapshotTicket.id).where(
            ScanDeviceSnapshotTicket.snapshot_id == snapshot.id,
            ScanDeviceSnapshotTicket.ticket_id == ticket.id,
        )) is None:
            reason = "ticket_issued_after_snapshot"
        elif ticket.status != TicketStatus.ACTIVE:
            reason = "ticket_revoked"
        elif event.status != EventStatus.IN_PROGRESS:
            reason = "event_not_in_progress"
        elif _utc(scanned_at) > datetime.now(timezone.utc) + timedelta(minutes=5):
            reason = "scan_time_in_future"
        prior_scan = db.scalar(select(AttendanceEvent).where(AttendanceEvent.scan_event_id == scan["scan_event_id"]))
        if prior_scan is not None:
            if ticket is not None and prior_scan.event_id == event_id and prior_scan.ticket_id == ticket.id:
                outcomes.append({"scan_event_id": str(scan["scan_event_id"]), "status": "duplicate"})
                continue
            reason = "scan_id_already_used"
        if reason is None:
            existing = db.scalar(select(AttendanceEvent).where(
                AttendanceEvent.event_id == event_id, AttendanceEvent.ticket_id == ticket.id,
                AttendanceEvent.event_type == AttendanceEventType.CHECK_IN
            ))
            if existing:
                reason = "ticket_already_checked_in"
        if reason is None:
            attendance = AttendanceEvent(event_id=event_id, ticket_id=ticket.id,
                event_type=AttendanceEventType.CHECK_IN, scan_event_id=scan["scan_event_id"],
                recorded_by_id=device.created_by_id, scanned_at=scanned_at, source="offline")
            db.add(attendance)
            db.flush()
            outcomes.append({"scan_event_id": str(scan["scan_event_id"]), "status": "accepted", "attendance_event_id": str(attendance.id)})
        else:
            conflict = db.scalar(select(OfflineScanConflict).where(
                OfflineScanConflict.scan_event_id == scan["scan_event_id"]
            ))
            if conflict is None:
                conflict = OfflineScanConflict(event_id=event_id, device_id=device.id, sync_batch_id=batch.id,
                    scan_event_id=scan["scan_event_id"], ticket_id=ticket.id if ticket else None,
                    credential_hash=credential_hash, scanned_at=scanned_at, reason=reason)
                db.add(conflict)
                db.flush()
            outcomes.append({"scan_event_id": str(scan["scan_event_id"]), "status": "conflict",
                             "conflict_id": str(conflict.id), "reason": conflict.reason})
    result = {"batch_id": str(payload["batch_id"]), "outcomes": outcomes}
    batch.result = result
    db.commit()
    return result


def list_offline_conflicts(db: Session, workspace_id: UUID, event_id: UUID):
    event = db.scalar(select(Event).where(Event.id == event_id, Event.workspace_id == workspace_id))
    if event is None:
        raise EventNotFound
    rows = db.execute(select(OfflineScanConflict, Registration.full_name).outerjoin(
        Ticket, Ticket.id == OfflineScanConflict.ticket_id
    ).outerjoin(Registration, Registration.id == Ticket.registration_id).where(
        OfflineScanConflict.event_id == event_id
    ).order_by(OfflineScanConflict.created_at.desc())).all()
    return rows


def resolve_offline_conflict(db: Session, workspace_id: UUID, event_id: UUID, conflict_id: UUID,
                             user_id: UUID, action: str, note: str | None):
    conflict = db.scalar(select(OfflineScanConflict).join(Event, Event.id == OfflineScanConflict.event_id).where(
        OfflineScanConflict.id == conflict_id, OfflineScanConflict.event_id == event_id,
        Event.workspace_id == workspace_id
    ).with_for_update())
    if conflict is None:
        raise EventNotFound
    if conflict.status != OfflineConflictStatus.PENDING:
        raise EventConflict("Conflict has already been resolved")
    if action == "accept":
        ticket = db.scalar(select(Ticket).where(Ticket.id == conflict.ticket_id).with_for_update()) if conflict.ticket_id else None
        event = db.get(Event, event_id)
        if conflict.reason not in {"ticket_issued_after_snapshot", "event_not_in_progress"}:
            raise EventConflict("This conflict reason cannot be accepted manually")
        if ticket is None or ticket.status != TicketStatus.ACTIVE or event.status != EventStatus.IN_PROGRESS:
            raise EventConflict("Ticket or event is no longer eligible for check-in")
        if _utc(conflict.scanned_at) > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise EventConflict("A future-dated scan cannot be accepted")
        if db.scalar(select(AttendanceEvent.id).where(
            (AttendanceEvent.scan_event_id == conflict.scan_event_id)
            | ((AttendanceEvent.event_id == event_id) & (AttendanceEvent.ticket_id == ticket.id))
        )):
            raise EventConflict("Ticket or scan has already been recorded")
        db.add(AttendanceEvent(event_id=event_id, ticket_id=ticket.id,
            event_type=AttendanceEventType.CHECK_IN, scan_event_id=conflict.scan_event_id,
            recorded_by_id=user_id, scanned_at=conflict.scanned_at, source="offline"))
        conflict.status = OfflineConflictStatus.ACCEPTED
    else:
        conflict.status = OfflineConflictStatus.IGNORED
    conflict.resolution_note = note
    conflict.resolved_by_id = user_id
    conflict.resolved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(conflict)
    return conflict
