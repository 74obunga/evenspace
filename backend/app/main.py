from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.health import router as health_router
from app.modules.events.routes import attendance_router, event_router, public_event_router, ticket_router
from app.modules.identity.routes import auth_router, workspace_router
from app.core.config import get_settings
from app.modules.payments.routes import refund_router, router as payment_router
from app.modules.meetings.routes import public_router as public_meeting_router, router as meeting_router
from app.modules.notifications.routes import router as notification_router

app = FastAPI(title=get_settings().app_name, version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(get_settings().frontend_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Idempotency-Key", "X-CSRF-Token", "X-Scan-Device-Token"],
)
app.include_router(health_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(workspace_router, prefix="/api/v1")
app.include_router(event_router, prefix="/api/v1")
app.include_router(public_event_router, prefix="/api/v1")
app.include_router(ticket_router, prefix="/api/v1")
app.include_router(attendance_router, prefix="/api/v1")
app.include_router(payment_router, prefix="/api/v1")
app.include_router(refund_router, prefix="/api/v1")
app.include_router(meeting_router, prefix="/api/v1")
app.include_router(public_meeting_router, prefix="/api/v1")
app.include_router(notification_router, prefix="/api/v1")

