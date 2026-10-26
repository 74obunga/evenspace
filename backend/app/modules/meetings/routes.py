from uuid import UUID
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.identity.dependencies import AuthContext, require_csrf, require_workspace_manager
from app.modules.meetings import service
from app.modules.meetings.schemas import (
    ActionHistoryResponse, ActionItemCreate, ActionItemResponse, ActionStatusChange,
    AgendaItemCreate, AgendaItemResponse, AttachmentResponse, AttendanceChange, DecisionCreate, DecisionResolve, DecisionResponse,
    InviteeCreate, InviteeResponse,
    MeetingCreate, MeetingScheduleCreate, MeetingGuestAttendanceChange, MeetingGuestManualCreate, MeetingGuestRegistrationCreate,
    MeetingGuestJoinResponse, MeetingGuestRegistrationResponse, MeetingJoinInfo, MeetingJoinLinkResponse, MeetingJoinTokenRequest,
    MeetingResponse, MeetingStatusChange, MinutesCreate, MinutesDecision, MinutesResponse,
)

router = APIRouter(prefix="/workspaces/{workspace_id}/meetings", tags=["meetings"])
public_router = APIRouter(prefix="/public/meetings", tags=["public meetings"])
MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024
ALLOWED_ATTACHMENT_TYPES = {
    "application/pdf", "image/jpeg", "image/png", "text/plain",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except service.MeetingNotFound:
        raise HTTPException(status_code=404, detail="Meeting record not found") from None
    except service.MeetingConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@router.post("", response_model=MeetingResponse, status_code=201)
def post_meeting(workspace_id: UUID, payload: MeetingCreate,
                 context: AuthContext = Depends(require_workspace_manager),
                 _csrf: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)):
    return _call(service.create_meeting, db, workspace_id, context.user.id, payload.model_dump())


@router.post("/schedule", response_model=MeetingResponse, status_code=201)
def post_scheduled_meeting(workspace_id: UUID, payload: MeetingScheduleCreate,
                           context: AuthContext = Depends(require_workspace_manager),
                           _csrf: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)):
    return _call(service.create_scheduled_meeting, db, workspace_id, context.user.id, payload.model_dump())


@router.get("", response_model=list[MeetingResponse])
def get_meetings(workspace_id: UUID,
                 _manager: AuthContext = Depends(require_workspace_manager), db: Session = Depends(get_db)):
    return _call(service.list_meetings, db, workspace_id)


@router.get("/{meeting_id}", response_model=MeetingResponse)
def get_meeting(workspace_id: UUID, meeting_id: UUID,
                _manager: AuthContext = Depends(require_workspace_manager), db: Session = Depends(get_db)):
    return _call(service.get_meeting, db, workspace_id, meeting_id)


@router.post("/{meeting_id}/status", response_model=MeetingResponse)
def change_meeting_status(workspace_id: UUID, meeting_id: UUID, payload: MeetingStatusChange,
                          _manager: AuthContext = Depends(require_workspace_manager),
                          _csrf: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)):
    return _call(service.transition_meeting, db, workspace_id, meeting_id, payload.status, payload.note)


@router.post("/{meeting_id}/join-link", response_model=MeetingJoinLinkResponse)
def post_join_link(workspace_id: UUID, meeting_id: UUID,
                   _manager: AuthContext = Depends(require_workspace_manager),
                   _csrf: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)):
    token = _call(service.generate_guest_join_token, db, workspace_id, meeting_id)
    return MeetingJoinLinkResponse(meeting_id=meeting_id, token=token)


@router.delete("/{meeting_id}/join-link", status_code=204)
def delete_join_link(workspace_id: UUID, meeting_id: UUID,
                     _manager: AuthContext = Depends(require_workspace_manager),
                     _csrf: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)):
    _call(service.revoke_guest_join_token, db, workspace_id, meeting_id)
    return Response(status_code=204)


@router.get("/{meeting_id}/guest-registrations", response_model=list[MeetingGuestRegistrationResponse])
def get_guest_registrations(workspace_id: UUID, meeting_id: UUID,
                            _manager: AuthContext = Depends(require_workspace_manager),
                            db: Session = Depends(get_db)):
    return _call(service.list_guest_registrations, db, workspace_id, meeting_id)


@router.post("/{meeting_id}/guest-registrations", response_model=MeetingGuestRegistrationResponse, status_code=201)
def post_manual_guest_registration(workspace_id: UUID, meeting_id: UUID, payload: MeetingGuestManualCreate,
                                   context: AuthContext = Depends(require_workspace_manager),
                                   _csrf: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)):
    return _call(service.add_manual_meeting_guest, db, workspace_id, meeting_id, context.user.id,
                 payload.model_dump())


@router.get("/{meeting_id}/guest-registrations/{guest_id}/signature")
def get_guest_signature(workspace_id: UUID, meeting_id: UUID, guest_id: UUID,
                        _manager: AuthContext = Depends(require_workspace_manager), db: Session = Depends(get_db)):
    signature = _call(service.get_guest_signature, db, workspace_id, meeting_id, guest_id)
    return Response(content=signature, media_type="image/png", headers={
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
    })


@router.delete("/{meeting_id}/guest-registrations/{guest_id}/privacy-data",
               response_model=MeetingGuestRegistrationResponse)
def delete_guest_privacy_data(workspace_id: UUID, meeting_id: UUID, guest_id: UUID,
                              _manager: AuthContext = Depends(require_workspace_manager),
                              _csrf: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)):
    return _call(service.erase_guest_privacy_data, db, workspace_id, meeting_id, guest_id)


@router.post("/{meeting_id}/guest-registrations/{guest_id}/attendance",
             response_model=MeetingGuestRegistrationResponse)
def post_guest_attendance(workspace_id: UUID, meeting_id: UUID, guest_id: UUID,
                          payload: MeetingGuestAttendanceChange,
                          context: AuthContext = Depends(require_workspace_manager),
                          _csrf: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)):
    return _call(service.record_guest_attendance, db, workspace_id, meeting_id, guest_id,
                 context.user.id, payload.status, payload.note)


@public_router.post("/{meeting_id}/join-info", response_model=MeetingJoinInfo)
def post_join_info(meeting_id: UUID, payload: MeetingJoinTokenRequest, db: Session = Depends(get_db)):
    return _call(service.get_guest_join_info, db, meeting_id, payload.token)


@public_router.post("/{meeting_id}/join", response_model=MeetingGuestJoinResponse, status_code=201)
def post_guest_join(meeting_id: UUID, payload: MeetingGuestRegistrationCreate, response: Response,
                    db: Session = Depends(get_db)):
    guest, created, join_url = _call(service.register_meeting_guest, db, meeting_id, payload.model_dump())
    if not created:
        response.status_code = 200
    return MeetingGuestJoinResponse(registration=guest, join_url=join_url)


@router.get("/{meeting_id}/invitees", response_model=list[InviteeResponse])
def get_invitees(workspace_id: UUID, meeting_id: UUID,
                 _manager: AuthContext = Depends(require_workspace_manager), db: Session = Depends(get_db)):
    return _call(service.list_invitees, db, workspace_id, meeting_id)


@router.post("/{meeting_id}/invitees", response_model=InviteeResponse, status_code=201)
def post_invitee(workspace_id: UUID, meeting_id: UUID, payload: InviteeCreate,
                 context: AuthContext = Depends(require_workspace_manager),
                 _csrf: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)):
    return _call(service.add_invitee, db, workspace_id, meeting_id, context.user.id, payload.user_id)


@router.delete("/{meeting_id}/invitees/{invitee_id}", status_code=204)
def delete_invitee(workspace_id: UUID, meeting_id: UUID, invitee_id: UUID,
                   _manager: AuthContext = Depends(require_workspace_manager),
                   _csrf: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)):
    _call(service.remove_invitee, db, workspace_id, meeting_id, invitee_id)


@router.post("/{meeting_id}/invitees/{invitee_id}/attendance", response_model=InviteeResponse)
def post_attendance(workspace_id: UUID, meeting_id: UUID, invitee_id: UUID, payload: AttendanceChange,
                    context: AuthContext = Depends(require_workspace_manager),
                    _csrf: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)):
    return _call(service.record_attendance, db, workspace_id, meeting_id, invitee_id,
                 context.user.id, payload.status, payload.note)


@router.get("/{meeting_id}/attachments", response_model=list[AttachmentResponse])
def get_attachments(workspace_id: UUID, meeting_id: UUID,
                    _manager: AuthContext = Depends(require_workspace_manager), db: Session = Depends(get_db)):
    return _call(service.list_attachments, db, workspace_id, meeting_id)


@router.post("/{meeting_id}/attachments", response_model=AttachmentResponse, status_code=201)
async def post_attachment(workspace_id: UUID, meeting_id: UUID, file: UploadFile = File(...),
                          context: AuthContext = Depends(require_workspace_manager),
                          _csrf: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)):
    if file.content_type not in ALLOWED_ATTACHMENT_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported attachment type")
    content = await file.read(MAX_ATTACHMENT_SIZE + 1)
    if len(content) > MAX_ATTACHMENT_SIZE:
        raise HTTPException(status_code=413, detail="Attachment exceeds the 10 MB limit")
    return _call(service.add_attachment, db, workspace_id, meeting_id, context.user.id,
                 file.filename or "attachment", file.content_type, content)


@router.get("/{meeting_id}/attachments/{attachment_id}/download")
def download_attachment(workspace_id: UUID, meeting_id: UUID, attachment_id: UUID,
                        _manager: AuthContext = Depends(require_workspace_manager), db: Session = Depends(get_db)):
    attachment = _call(service.get_attachment, db, workspace_id, meeting_id, attachment_id)
    filename = quote(attachment.filename, safe="")
    return Response(
        content=attachment.content,
        media_type=attachment.media_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.delete("/{meeting_id}/attachments/{attachment_id}", status_code=204)
def remove_attachment(workspace_id: UUID, meeting_id: UUID, attachment_id: UUID,
                       _manager: AuthContext = Depends(require_workspace_manager),
                       _csrf: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)):
    _call(service.delete_attachment, db, workspace_id, meeting_id, attachment_id)


@router.get("/{meeting_id}/agenda", response_model=list[AgendaItemResponse])
def get_agenda(workspace_id: UUID, meeting_id: UUID,
               _manager: AuthContext = Depends(require_workspace_manager), db: Session = Depends(get_db)):
    return _call(service.list_agenda, db, workspace_id, meeting_id)


@router.post("/{meeting_id}/agenda", response_model=AgendaItemResponse, status_code=201)
def post_agenda(workspace_id: UUID, meeting_id: UUID, payload: AgendaItemCreate,
                context: AuthContext = Depends(require_workspace_manager),
                _csrf: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)):
    return _call(service.add_agenda_item, db, workspace_id, meeting_id, context.user.id, payload.model_dump())


@router.delete("/{meeting_id}/agenda/{item_id}", status_code=204)
def remove_agenda(workspace_id: UUID, meeting_id: UUID, item_id: UUID,
                  _manager: AuthContext = Depends(require_workspace_manager),
                  _csrf: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)):
    _call(service.delete_agenda_item, db, workspace_id, meeting_id, item_id)


@router.get("/{meeting_id}/minutes", response_model=list[MinutesResponse])
def get_minutes(workspace_id: UUID, meeting_id: UUID,
                _manager: AuthContext = Depends(require_workspace_manager), db: Session = Depends(get_db)):
    return _call(service.list_minutes, db, workspace_id, meeting_id)


@router.post("/{meeting_id}/minutes", response_model=MinutesResponse, status_code=201)
def post_minutes(workspace_id: UUID, meeting_id: UUID, payload: MinutesCreate,
                 context: AuthContext = Depends(require_workspace_manager),
                 _csrf: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)):
    return _call(service.create_minutes_revision, db, workspace_id, meeting_id, context.user.id, payload.content)


@router.put("/{meeting_id}/minutes/{revision_id}", response_model=MinutesResponse)
def put_minutes(workspace_id: UUID, meeting_id: UUID, revision_id: UUID, payload: MinutesCreate,
                _manager: AuthContext = Depends(require_workspace_manager),
                _csrf: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)):
    return _call(service.edit_minutes, db, workspace_id, meeting_id, revision_id, payload.content)


@router.post("/{meeting_id}/minutes/{revision_id}/submit", response_model=MinutesResponse)
def submit_minutes(workspace_id: UUID, meeting_id: UUID, revision_id: UUID,
                   _manager: AuthContext = Depends(require_workspace_manager),
                   _csrf: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)):
    return _call(service.submit_minutes, db, workspace_id, meeting_id, revision_id)


@router.post("/{meeting_id}/minutes/{revision_id}/approve", response_model=MinutesResponse)
def approve_minutes(workspace_id: UUID, meeting_id: UUID, revision_id: UUID, payload: MinutesDecision,
                    context: AuthContext = Depends(require_workspace_manager),
                    _csrf: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)):
    return _call(service.decide_minutes, db, workspace_id, meeting_id, revision_id, context.user.id,
                 approve=True, note=payload.note)


@router.post("/{meeting_id}/minutes/{revision_id}/reject", response_model=MinutesResponse)
def reject_minutes(workspace_id: UUID, meeting_id: UUID, revision_id: UUID, payload: MinutesDecision,
                   context: AuthContext = Depends(require_workspace_manager),
                   _csrf: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)):
    return _call(service.decide_minutes, db, workspace_id, meeting_id, revision_id, context.user.id,
                 approve=False, note=payload.note)


@router.get("/{meeting_id}/decisions", response_model=list[DecisionResponse])
def get_decisions(workspace_id: UUID, meeting_id: UUID,
                  _manager: AuthContext = Depends(require_workspace_manager), db: Session = Depends(get_db)):
    return _call(service.list_decisions, db, workspace_id, meeting_id)


@router.post("/{meeting_id}/decisions", response_model=DecisionResponse, status_code=201)
def post_decision(workspace_id: UUID, meeting_id: UUID, payload: DecisionCreate,
                  context: AuthContext = Depends(require_workspace_manager),
                  _csrf: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)):
    return _call(service.create_decision, db, workspace_id, meeting_id, context.user.id, payload.model_dump())


@router.post("/{meeting_id}/decisions/{decision_id}/resolve", response_model=DecisionResponse)
def resolve_decision(workspace_id: UUID, meeting_id: UUID, decision_id: UUID, payload: DecisionResolve,
                     context: AuthContext = Depends(require_workspace_manager),
                     _csrf: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)):
    return _call(service.resolve_decision, db, workspace_id, meeting_id, decision_id,
                 context.user.id, payload.result, payload.note)


@router.get("/{meeting_id}/action-items", response_model=list[ActionItemResponse])
def get_actions(workspace_id: UUID, meeting_id: UUID,
                _manager: AuthContext = Depends(require_workspace_manager), db: Session = Depends(get_db)):
    return _call(service.list_action_items, db, workspace_id, meeting_id)


@router.post("/{meeting_id}/action-items", response_model=ActionItemResponse, status_code=201)
def post_action(workspace_id: UUID, meeting_id: UUID, payload: ActionItemCreate,
                context: AuthContext = Depends(require_workspace_manager),
                _csrf: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)):
    return _call(service.create_action_item, db, workspace_id, meeting_id, context.user.id, payload.model_dump())


@router.post("/{meeting_id}/action-items/{action_id}/status", response_model=ActionItemResponse)
def change_action_status(workspace_id: UUID, meeting_id: UUID, action_id: UUID, payload: ActionStatusChange,
                         context: AuthContext = Depends(require_workspace_manager),
                         _csrf: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)):
    return _call(service.transition_action_item, db, workspace_id, meeting_id, action_id,
                 context.user.id, payload.status, payload.note)


@router.get("/{meeting_id}/action-items/{action_id}/history", response_model=list[ActionHistoryResponse])
def get_action_history(workspace_id: UUID, meeting_id: UUID, action_id: UUID,
                       _manager: AuthContext = Depends(require_workspace_manager), db: Session = Depends(get_db)):
    return _call(service.list_action_history, db, workspace_id, meeting_id, action_id)
