from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.db.session import get_db
from app.modules.events.models import Event, Registration, Ticket, TicketType
from app.modules.events.schemas import (
    AttendanceCheckInRequest,
    AttendanceCheckInResponse,
    AttendanceRecordResponse,
    EventCreateRequest,
    EventUpdateRequest,
    EventCancelRequest,
    EventResponse,
    OperatorAssignmentResponse,
    OrganizerEventResponse,
    ParticipantTicketResponse,
    PublicEventResponse,
    PublicRegistrationRequest,
    PublicTicketTypeResponse,
    RegistrationResponse,
    TicketRevokeResponse,
    TicketTypeCreateRequest,
    TicketLookupRequest,
    TicketTypeResponse,
    OrganizerRegistrationResponse,
    ScanDeviceCreateRequest, ScanDeviceResponse, ScanDeviceItemResponse, OfflineManifestResponse,
    OfflineSyncRequest, OfflineConflictResponse, OfflineConflictResolveRequest,
)
from app.modules.events.service import (
    AttendanceForbidden,
    CapacityReached,
    EventConflict,
    EventNotFound,
    TicketTypeNotFound,
    add_free_ticket_type,
    assign_operator,
    check_in_ticket,
    manual_check_in_registration,
    create_event,
    update_workspace_event,
    cancel_workspace_event,
    get_participant_ticket,
    get_public_event,
    get_workspace_event,
    list_workspace_events,
    list_public_events,
    list_attendance,
    publish_event,
    remove_operator,
    register_participant,
    revoke_ticket,
    start_event,
    create_scan_device, list_scan_devices, revoke_scan_device, create_offline_manifest, sync_offline_batch,
    list_offline_conflicts, resolve_offline_conflict,
    list_event_registrations,
)
from app.modules.identity.dependencies import (
    AuthContext,
    get_auth_context,
    get_workspace_for_member,
    require_csrf,
    require_workspace_event_manager,
)
from app.modules.identity.models import Workspace
from pydantic import UUID4

event_router = APIRouter(prefix="/workspaces/{workspace_id}/events", tags=["events"])
public_event_router = APIRouter(prefix="/public/events", tags=["public events"])
ticket_router = APIRouter(prefix="/public/tickets", tags=["participant tickets"])
attendance_router = APIRouter(prefix="/events/{event_id}/attendance", tags=["attendance"])


def _ticket_response(ticket_type: TicketType) -> TicketTypeResponse:
    return TicketTypeResponse(
        id=ticket_type.id,
        name=ticket_type.name,
        description=ticket_type.description,
        price=ticket_type.price,
        capacity=ticket_type.capacity,
        registration_count=ticket_type.registration_count,
    )


def _organizer_event_response(event: Event) -> OrganizerEventResponse:
    return OrganizerEventResponse(
        id=event.id,
        workspace_id=event.workspace_id,
        title=event.title,
        description=event.description,
        category=event.category,
        status=event.status.value,
        visibility=event.visibility.value,
        start_at=event.start_at,
        end_at=event.end_at,
        timezone=event.timezone,
        registration_open_at=event.registration_open_at,
        registration_close_at=event.registration_close_at,
        capacity=event.capacity,
        registration_count=event.registration_count,
        ticket_types=[_ticket_response(item) for item in event.ticket_types],
    )


def _event_response(event: Event) -> EventResponse:
    return EventResponse(
        id=event.id,
        workspace_id=event.workspace_id,
        title=event.title,
        description=event.description,
        category=event.category,
        status=event.status.value,
        visibility=event.visibility.value,
        start_at=event.start_at,
        end_at=event.end_at,
        timezone=event.timezone,
        registration_open_at=event.registration_open_at,
        registration_close_at=event.registration_close_at,
        capacity=event.capacity,
        registration_count=event.registration_count,
    )


@event_router.get("", response_model=list[OrganizerEventResponse])
def get_events(
    workspace: Workspace = Depends(get_workspace_for_member),
    db: Session = Depends(get_db),
):
    return [_organizer_event_response(item) for item in list_workspace_events(db, workspace.id)]


@event_router.post("", response_model=EventResponse, status_code=201)
def post_event(
    workspace_id: UUID,
    payload: EventCreateRequest,
    _csrf_context: AuthContext = Depends(require_csrf),
    context: AuthContext = Depends(require_workspace_event_manager),
    db: Session = Depends(get_db),
):
    event = create_event(db, workspace_id, context.user.id, payload.model_dump())
    return _event_response(event)


@event_router.post("/{event_id}/ticket-types", response_model=TicketTypeResponse, status_code=201)
def post_ticket_type(
    workspace_id: UUID,
    event_id: UUID,
    payload: TicketTypeCreateRequest,
    _csrf_context: AuthContext = Depends(require_csrf),
    _manager_context: AuthContext = Depends(require_workspace_event_manager),
    db: Session = Depends(get_db),
):
    try:
        ticket_type = add_free_ticket_type(db, workspace_id, event_id, payload.model_dump())
    except EventNotFound:
        raise HTTPException(status_code=404, detail="Event not found") from None
    except EventConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return _ticket_response(ticket_type)


@event_router.put("/{event_id}", response_model=EventResponse)
def put_event(workspace_id: UUID, event_id: UUID, payload: EventUpdateRequest,
              _csrf: AuthContext = Depends(require_csrf),
              _manager: AuthContext = Depends(require_workspace_event_manager), db: Session = Depends(get_db)):
    try:
        event = update_workspace_event(db, workspace_id, event_id, payload.model_dump(exclude_unset=True))
    except EventNotFound:
        raise HTTPException(status_code=404, detail="Event not found") from None
    except EventConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return _event_response(event)


@event_router.post("/{event_id}/cancel", response_model=EventResponse)
def post_cancel_event(workspace_id: UUID, event_id: UUID, payload: EventCancelRequest,
                      _csrf: AuthContext = Depends(require_csrf),
                      _manager: AuthContext = Depends(require_workspace_event_manager), db: Session = Depends(get_db)):
    try:
        event = cancel_workspace_event(db, workspace_id, event_id, payload.reason)
    except EventNotFound:
        raise HTTPException(status_code=404, detail="Event not found") from None
    except EventConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return _event_response(event)


@event_router.post("/{event_id}/publish", response_model=EventResponse)
def post_publish_event(
    workspace_id: UUID,
    event_id: UUID,
    _csrf_context: AuthContext = Depends(require_csrf),
    _manager_context: AuthContext = Depends(require_workspace_event_manager),
    db: Session = Depends(get_db),
):
    try:
        event = publish_event(db, workspace_id, event_id)
    except EventNotFound:
        raise HTTPException(status_code=404, detail="Event not found") from None
    except EventConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return _event_response(event)


@event_router.post("/{event_id}/start", response_model=EventResponse)
def post_start_event(
    workspace_id: UUID,
    event_id: UUID,
    _csrf_context: AuthContext = Depends(require_csrf),
    _manager_context: AuthContext = Depends(require_workspace_event_manager),
    db: Session = Depends(get_db),
):
    try:
        return _event_response(start_event(db, workspace_id, event_id))
    except EventNotFound:
        raise HTTPException(status_code=404, detail="Event not found") from None
    except EventConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@event_router.post("/{event_id}/operators/{user_id}", response_model=OperatorAssignmentResponse)
def post_assign_operator(
    workspace_id: UUID,
    event_id: UUID,
    user_id: UUID,
    _csrf_context: AuthContext = Depends(require_csrf),
    context: AuthContext = Depends(require_workspace_event_manager),
    db: Session = Depends(get_db),
):
    try:
        assignment = assign_operator(db, workspace_id, event_id, user_id, context.user.id)
    except EventNotFound:
        raise HTTPException(status_code=404, detail="Event not found") from None
    except EventConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return OperatorAssignmentResponse(
        event_id=assignment.event_id, user_id=assignment.user_id, assigned_at=assignment.assigned_at
    )


@event_router.delete("/{event_id}/operators/{user_id}", status_code=204)
def delete_operator(
    workspace_id: UUID,
    event_id: UUID,
    user_id: UUID,
    _csrf_context: AuthContext = Depends(require_csrf),
    _manager_context: AuthContext = Depends(require_workspace_event_manager),
    db: Session = Depends(get_db),
):
    try:
        remove_operator(db, workspace_id, event_id, user_id)
    except EventNotFound:
        raise HTTPException(status_code=404, detail="Event or assignment not found") from None
    return Response(status_code=204)


@event_router.post("/{event_id}/tickets/{ticket_id}/revoke", response_model=TicketRevokeResponse)
def post_revoke_ticket(
    workspace_id: UUID,
    event_id: UUID,
    ticket_id: UUID,
    _csrf_context: AuthContext = Depends(require_csrf),
    _manager_context: AuthContext = Depends(require_workspace_event_manager),
    db: Session = Depends(get_db),
):
    try:
        ticket = revoke_ticket(db, workspace_id, event_id, ticket_id)
    except TicketTypeNotFound:
        raise HTTPException(status_code=404, detail="Ticket not found") from None
    return TicketRevokeResponse(id=ticket.id, status=ticket.status.value, revoked_at=ticket.revoked_at)


@event_router.get("/{event_id}", response_model=OrganizerEventResponse)
def get_event(
    workspace_id: UUID,
    event_id: UUID,
    _workspace: Workspace = Depends(get_workspace_for_member),
    db: Session = Depends(get_db),
):
    try:
        return _organizer_event_response(get_workspace_event(db, workspace_id, event_id))
    except EventNotFound:
        raise HTTPException(status_code=404, detail="Event not found") from None


@event_router.get("/{event_id}/registrations", response_model=list[OrganizerRegistrationResponse])
def get_event_registrations(workspace_id: UUID, event_id: UUID,
                            _manager: AuthContext = Depends(require_workspace_event_manager),
                            db: Session = Depends(get_db)):
    try:
        rows = list_event_registrations(db, workspace_id, event_id)
    except EventNotFound:
        raise HTTPException(status_code=404, detail="Event not found") from None
    return [OrganizerRegistrationResponse(
        id=registration.id, full_name=registration.full_name, email=registration.email,
        status=registration.status.value, ticket_type=ticket_type,
        ticket_status=ticket_status.value if ticket_status else None,
        registered_at=registration.registered_at, checked_in_at=checked_in_at,
    ) for registration, ticket_type, ticket_status, checked_in_at in rows]


@event_router.post("/{event_id}/registrations/{registration_id}/manual-check-in", response_model=AttendanceCheckInResponse)
def post_manual_check_in(workspace_id: UUID, event_id: UUID, registration_id: UUID,
                         context: AuthContext = Depends(require_workspace_event_manager),
                         _csrf: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)):
    try:
        attendance, ticket, registration, duplicate = manual_check_in_registration(
            db, workspace_id, event_id, registration_id, context.user.id
        )
    except EventNotFound:
        raise HTTPException(status_code=404, detail="Event or registration not found") from None
    except EventConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return AttendanceCheckInResponse(
        attendance_event_id=attendance.id,
        event_id=event_id,
        ticket_id=ticket.id,
        attendee_name=registration.full_name,
        event_type=attendance.event_type.value,
        scanned_at=attendance.scanned_at,
        duplicate=duplicate,
    )


@public_event_router.get("/{event_id}", response_model=PublicEventResponse)
def get_public_event_endpoint(event_id: UUID, db: Session = Depends(get_db)):
    try:
        event = get_public_event(db, event_id)
    except EventNotFound:
        raise HTTPException(status_code=404, detail="Event not found") from None
    return PublicEventResponse(
        id=event.id,
        title=event.title,
        description=event.description,
        category=event.category,
        start_at=event.start_at,
        end_at=event.end_at,
        timezone=event.timezone,
        capacity=event.capacity,
        registration_close_at=event.registration_close_at,
        ticket_types=[
            PublicTicketTypeResponse(
                id=item.id, name=item.name, description=item.description,
                price=item.price, capacity=item.capacity,
            )
            for item in event.ticket_types if item.is_active
        ],
    )


@public_event_router.get("", response_model=list[PublicEventResponse])
def list_public_events_endpoint(db: Session = Depends(get_db)):
    return [
        PublicEventResponse(
            id=event.id,
            title=event.title,
            description=event.description,
            category=event.category,
            start_at=event.start_at,
            end_at=event.end_at,
            timezone=event.timezone,
            capacity=event.capacity,
            registration_close_at=event.registration_close_at,
            ticket_types=[
                PublicTicketTypeResponse(
                    id=item.id, name=item.name, description=item.description,
                    price=item.price, capacity=item.capacity,
                )
                for item in event.ticket_types
                if item.is_active and (item.capacity is None or item.registration_count < item.capacity)
            ],
        )
        for event in list_public_events(db)
    ]


@public_event_router.post("/{event_id}/registrations", response_model=RegistrationResponse, status_code=201)
def post_public_registration(
    event_id: UUID,
    payload: PublicRegistrationRequest,
    response: Response,
    idempotency_key: UUID4 = Header(alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    try:
        registration, ticket, created, credential = register_participant(
            db, event_id, payload.ticket_type_id, payload.full_name, payload.email, str(idempotency_key)
        )
    except EventNotFound:
        raise HTTPException(status_code=404, detail="Event not found") from None
    except TicketTypeNotFound:
        raise HTTPException(status_code=404, detail="Ticket type not found for this event") from None
    except CapacityReached as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except EventConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    if not created:
        response.status_code = 200
    return RegistrationResponse(
        id=registration.id,
        event_id=registration.event_id,
        ticket_type_id=registration.ticket_type_id,
        ticket_id=ticket.id,
        ticket_credential=credential,
        full_name=registration.full_name,
        email=registration.email,
        status=registration.status.value,
        confirmation_code=registration.confirmation_code,
        registered_at=registration.registered_at,
    )


@ticket_router.post("/lookup", response_model=ParticipantTicketResponse)
def lookup_ticket(payload: TicketLookupRequest, db: Session = Depends(get_db)):
    row = get_participant_ticket(db, payload.credential)
    if row is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    ticket, event, registration, ticket_type = row
    return ParticipantTicketResponse(
        ticket_id=ticket.id,
        event_id=event.id,
        event_title=event.title,
        start_at=event.start_at,
        end_at=event.end_at,
        timezone=event.timezone,
        ticket_type_name=ticket_type.name,
        attendee_name=registration.full_name,
        status=ticket.status.value,
    )


@attendance_router.post("/check-in", response_model=AttendanceCheckInResponse)
def post_check_in(
    event_id: UUID,
    payload: AttendanceCheckInRequest,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    try:
        attendance, ticket, registration, duplicate = check_in_ticket(
            db, event_id, context.user.id, payload.ticket_credential, payload.scan_event_id
        )
    except EventNotFound:
        raise HTTPException(status_code=404, detail="Event not found") from None
    except TicketTypeNotFound:
        raise HTTPException(status_code=404, detail="Ticket is invalid or revoked") from None
    except AttendanceForbidden:
        raise HTTPException(status_code=403, detail="Operator is not assigned to this event") from None
    except EventConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return AttendanceCheckInResponse(
        attendance_event_id=attendance.id,
        event_id=attendance.event_id,
        ticket_id=ticket.id,
        attendee_name=registration.full_name,
        event_type=attendance.event_type.value,
        scanned_at=attendance.scanned_at,
        duplicate=duplicate,
    )


@event_router.get("/{event_id}/attendance", response_model=list[AttendanceRecordResponse])
def get_event_attendance(
    workspace_id: UUID,
    event_id: UUID,
    workspace: Workspace = Depends(get_workspace_for_member),
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
):
    try:
        rows = list_attendance(db, workspace.id, event_id, context.user.id)
    except EventNotFound:
        raise HTTPException(status_code=404, detail="Event not found") from None
    except AttendanceForbidden:
        raise HTTPException(status_code=403, detail="Attendance access denied") from None
    return [
        AttendanceRecordResponse(
            attendance_event_id=attendance.id,
            ticket_id=ticket.id,
            attendee_name=registration.full_name,
            scanned_at=attendance.scanned_at,
        )
        for attendance, ticket, registration in rows
    ]


@event_router.get("/{event_id}/scan-devices", response_model=list[ScanDeviceItemResponse])
def get_scan_devices(workspace_id: UUID, event_id: UUID,
                     _manager: AuthContext = Depends(require_workspace_event_manager),
                     db: Session = Depends(get_db)):
    try:
        devices = list_scan_devices(db, workspace_id, event_id)
    except EventNotFound:
        raise HTTPException(status_code=404, detail="Event not found") from None
    now = datetime.now(timezone.utc)
    return [
        ScanDeviceItemResponse(
            id=d.id,
            event_id=d.event_id,
            name=d.name,
            expires_at=d.expires_at,
            revoked_at=d.revoked_at,
            created_at=d.created_at,
            is_active=bool(d.revoked_at is None and (d.expires_at if d.expires_at.tzinfo else d.expires_at.replace(tzinfo=timezone.utc)) > now),
        )
        for d in devices
    ]


@event_router.post("/{event_id}/scan-devices", response_model=ScanDeviceResponse, status_code=201)
def post_scan_device(workspace_id: UUID, event_id: UUID, payload: ScanDeviceCreateRequest,
                     context: AuthContext = Depends(require_workspace_event_manager),
                     _csrf: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)):
    try:
        device, token = create_scan_device(db, workspace_id, event_id, context.user.id,
                                           payload.name, payload.expires_in_days)
    except EventNotFound:
        raise HTTPException(status_code=404, detail="Event not found") from None
    return ScanDeviceResponse(id=device.id, event_id=device.event_id, name=device.name,
                              token=token, expires_at=device.expires_at)


@event_router.delete("/{event_id}/scan-devices/{device_id}", status_code=204)
def delete_scan_device(workspace_id: UUID, event_id: UUID, device_id: UUID,
                       _manager: AuthContext = Depends(require_workspace_event_manager),
                       _csrf: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)):
    try:
        revoke_scan_device(db, workspace_id, event_id, device_id)
    except EventNotFound:
        raise HTTPException(status_code=404, detail="Device not found") from None
    return Response(status_code=204)


@attendance_router.get("/offline-manifest", response_model=OfflineManifestResponse)
def get_offline_manifest(event_id: UUID, x_scan_device_token: str = Header(alias="X-Scan-Device-Token"),
                         db: Session = Depends(get_db)):
    try:
        return create_offline_manifest(db, event_id, x_scan_device_token)
    except EventNotFound:
        raise HTTPException(status_code=404, detail="Event not found") from None
    except AttendanceForbidden:
        raise HTTPException(status_code=401, detail="Invalid or expired scan device token") from None


@attendance_router.post("/sync")
def post_offline_sync(event_id: UUID, payload: OfflineSyncRequest,
                      x_scan_device_token: str = Header(alias="X-Scan-Device-Token"),
                      db: Session = Depends(get_db)):
    try:
        return sync_offline_batch(db, event_id, x_scan_device_token, payload.model_dump())
    except EventNotFound:
        raise HTTPException(status_code=404, detail="Event not found") from None
    except AttendanceForbidden:
        raise HTTPException(status_code=401, detail="Invalid or expired scan device token") from None
    except EventConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@event_router.get("/{event_id}/attendance/conflicts", response_model=list[OfflineConflictResponse])
def get_offline_conflicts(workspace_id: UUID, event_id: UUID,
                          _manager: AuthContext = Depends(require_workspace_event_manager),
                          db: Session = Depends(get_db)):
    try:
        rows = list_offline_conflicts(db, workspace_id, event_id)
    except EventNotFound:
        raise HTTPException(status_code=404, detail="Event not found") from None
    return [OfflineConflictResponse(id=c.id, scan_event_id=c.scan_event_id, ticket_id=c.ticket_id,
        attendee_name=name, scanned_at=c.scanned_at, reason=c.reason, status=c.status.value,
        resolution_note=c.resolution_note) for c, name in rows]


@event_router.post("/{event_id}/attendance/conflicts/{conflict_id}/resolve", response_model=OfflineConflictResponse)
def post_resolve_offline_conflict(workspace_id: UUID, event_id: UUID, conflict_id: UUID,
                                  payload: OfflineConflictResolveRequest,
                                  context: AuthContext = Depends(require_workspace_event_manager),
                                  _csrf: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)):
    try:
        c = resolve_offline_conflict(db, workspace_id, event_id, conflict_id, context.user.id,
                                     payload.action, payload.note)
    except EventNotFound:
        raise HTTPException(status_code=404, detail="Conflict not found") from None
    except EventConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    name = db.scalar(select(Registration.full_name).join(Ticket, Ticket.registration_id == Registration.id)
                     .where(Ticket.id == c.ticket_id)) if c.ticket_id else None
    return OfflineConflictResponse(id=c.id, scan_event_id=c.scan_event_id, ticket_id=c.ticket_id,
        attendee_name=name, scanned_at=c.scanned_at, reason=c.reason, status=c.status.value,
        resolution_note=c.resolution_note)
