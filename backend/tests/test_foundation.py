from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.modules.identity.models import AuthSession, User, Workspace, WorkspaceMembership, WorkspaceRole
from app.modules.identity.security import hash_password, new_csrf_token, new_session_token, token_hash


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
    monkeypatch.setenv("NOTIFICATION_ENCRYPTION_KEY", "uE_d48N-N0G1e_5u5fFhD9V1-6cMfqfXo1FmG004k9s=")
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client, engine
    app.dependency_overrides.clear()
    engine.dispose()


def test_liveness_endpoint():
    response = TestClient(app).get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_membership_rejects_duplicate_workspace_user_pair():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        user = User(email="member@example.test", password_hash="test-only-hash")
        workspace = Workspace(name="Example")
        session.add_all([user, workspace])
        session.flush()
        session.add_all([
            WorkspaceMembership(user_id=user.id, workspace_id=workspace.id, role=WorkspaceRole.OWNER),
            WorkspaceMembership(user_id=user.id, workspace_id=workspace.id, role=WorkspaceRole.MEMBER),
        ])
        with pytest.raises(IntegrityError):
            session.commit()


def test_registration_csrf_protection_workspace_creation_and_logout(client):
    test_client, engine = client
    response = test_client.post("/api/v1/auth/register", json={
        "email": "owner@example.com",
        "password": "correct horse battery staple",
        "workspace_name": "First Workspace",
    })
    assert response.status_code == 201
    assert response.json()["workspace"]["role"] == "owner"

    # Self-registered accounts require verification before sign-in
    unverified_login = test_client.post("/api/v1/auth/login", json={
        "email": "owner@example.com",
        "password": "correct horse battery staple",
    })
    assert unverified_login.status_code == 403

    # Mark verified in database
    with Session(engine) as session:
        user = session.scalar(select(User).where(User.email == "owner@example.com"))
        assert user is not None
        user.email_verified_at = datetime.now(timezone.utc)
        session.commit()

    # Login succeeds and sets cookies
    login_response = test_client.post("/api/v1/auth/login", json={
        "email": "owner@example.com",
        "password": "correct horse battery staple",
    })
    assert login_response.status_code == 200
    assert test_client.cookies.get("evenspace_session")

    assert test_client.get("/api/v1/auth/me").status_code == 200
    assert test_client.post("/api/v1/workspaces", json={"name": "Second Workspace"}).status_code == 403

    csrf = test_client.cookies.get("evenspace_csrf")
    created = test_client.post("/api/v1/workspaces", json={"name": "Second Workspace"},
                               headers={"X-CSRF-Token": csrf})
    assert created.status_code == 201
    assert created.json()["role"] == "owner"

    logged_out = test_client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    assert logged_out.status_code == 204
    assert test_client.get("/api/v1/auth/me").status_code == 401


def test_login_is_throttled_after_five_failures(client):
    test_client, engine = client
    with Session(engine) as session:
        session.add(User(email="known@example.com", password_hash=hash_password("a sufficiently long password")))
        session.commit()

    for _ in range(5):
        response = test_client.post("/api/v1/auth/login", json={
            "email": "known@example.com", "password": "wrong password",
        })
        assert response.status_code == 401
    response = test_client.post("/api/v1/auth/login", json={
        "email": "known@example.com", "password": "wrong password",
    })
    assert response.status_code == 429


def test_member_cannot_read_another_workspace(client):
    test_client, engine = client
    with Session(engine) as session:
        member = User(email="member@example.test", password_hash="unused")
        other = User(email="other@example.test", password_hash="unused")
        own_workspace = Workspace(name="Member workspace")
        other_workspace = Workspace(name="Private workspace")
        session.add_all([member, other, own_workspace, other_workspace])
        session.flush()
        session.add_all([
            WorkspaceMembership(user_id=member.id, workspace_id=own_workspace.id, role=WorkspaceRole.OWNER),
            WorkspaceMembership(user_id=other.id, workspace_id=other_workspace.id, role=WorkspaceRole.OWNER),
        ])
        session_token, csrf = new_session_token(), new_csrf_token()
        session.add(AuthSession(user_id=member.id, token_hash=token_hash(session_token),
                                csrf_token_hash=token_hash(csrf),
                                expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
        session.commit()
        own_id, other_id = own_workspace.id, other_workspace.id
    test_client.cookies.set("evenspace_session", session_token)

    assert test_client.get(f"/api/v1/workspaces/{own_id}").status_code == 200
    assert test_client.get(f"/api/v1/workspaces/{other_id}").status_code == 404


def test_scanner_origin_can_make_device_token_requests(client):
    test_client, _engine = client
    response = test_client.options(
        "/api/v1/events/event-id/attendance/sync",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-scan-device-token",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "x-scan-device-token" in response.headers["access-control-allow-headers"].lower()

