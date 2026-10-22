from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.identity.dependencies import AuthContext, require_csrf, require_workspace_manager
from app.modules.notifications.models import NotificationAttempt
from app.modules.notifications.schemas import (
    NotificationAttemptResponse, NotificationResponse, TemplateResponse, TemplateUpdate,
)
from app.modules.notifications.service import list_notifications, list_templates, retry_notification, update_template

router = APIRouter(prefix="/workspaces/{workspace_id}/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationResponse])
def get_notifications(workspace_id: UUID, _manager: AuthContext = Depends(require_workspace_manager),
                      db: Session = Depends(get_db)):
    return list_notifications(db, workspace_id)


@router.get("/templates", response_model=list[TemplateResponse])
def get_templates(workspace_id: UUID, _manager: AuthContext = Depends(require_workspace_manager),
                  db: Session = Depends(get_db)):
    return list_templates(db, workspace_id)


@router.put("/templates/{key}", response_model=TemplateResponse)
def put_template(workspace_id: UUID, key: str, payload: TemplateUpdate,
                 context: AuthContext = Depends(require_workspace_manager),
                 _csrf: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)):
    try:
        return update_template(db, workspace_id, context.user.id, key, payload.subject_template,
                               payload.body_template, payload.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.get("/{notification_id}/attempts", response_model=list[NotificationAttemptResponse])
def get_attempts(workspace_id: UUID, notification_id: UUID,
                 _manager: AuthContext = Depends(require_workspace_manager), db: Session = Depends(get_db)):
    from app.modules.notifications.models import Notification
    exists = db.scalar(select(Notification.id).where(
        Notification.id == notification_id, Notification.workspace_id == workspace_id,
    ))
    if exists is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    return list(db.scalars(select(NotificationAttempt).where(
        NotificationAttempt.notification_id == notification_id,
    ).order_by(NotificationAttempt.attempt_number)))


@router.post("/{notification_id}/retry", response_model=NotificationResponse)
def post_retry(workspace_id: UUID, notification_id: UUID,
               _manager: AuthContext = Depends(require_workspace_manager),
               _csrf: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)):
    try:
        row = retry_notification(db, workspace_id, notification_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    if row is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    return row
