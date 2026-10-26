from datetime import datetime, timedelta, timezone
from decimal import Decimal
import base64
import struct
from uuid import UUID, uuid4
import zlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.modules.identity.models import User, Workspace, WorkspaceMembership, WorkspaceRole
from app.modules.identity.security import hash_password
from app.modules.meetings.models import MeetingGuestRegistration


def signature_data_url():
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    # One visible dark pixel is enough for a tiny, valid test signature image.
    png = (b"\x89PNG\r\n\x1a\n" +
           chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)) +
           chunk(b"IDAT", zlib.compress(b"\x00\x20\x70\x30\xff")) + chunk(b"IEND", b""))
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii"), png


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


def register_and_login(test_client, engine, email, password, workspace_name):
    account = test_client.post("/api/v1/auth/register", json={
        "email": email,
        "password": password,
        "workspace_name": workspace_name,
    })
    assert account.status_code == 201
    workspace_id = account.json()["workspace"]["id"]
    with Session(engine) as session:
        user = session.scalar(select(User).where(User.email == email.strip().casefold()))
        assert user is not None
        user.email_verified_at = datetime.now(timezone.utc)
        session.commit()
    login_resp = test_client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login_resp.status_code == 200
    csrf = test_client.cookies.get("evenspace_csrf")
    return workspace_id, csrf


def test_publish_and_free_registration_respects_capacity_and_is_idempotent(client):
    test_client, engine = client
    workspace_id, csrf = register_and_login(
        test_client, engine, "organizer@example.com", "correct horse battery staple", "Organizer"
    )
    headers = {"X-CSRF-Token": csrf}

    now = datetime.now(timezone.utc)
    start = now + timedelta(days=2)
    event_response = test_client.post(f"/api/v1/workspaces/{workspace_id}/events", headers=headers, json={
        "title": "Community Forum",
        "description": "A public forum",
        "category": "conference",
        "visibility": "public",
        "start_at": start.isoformat(),
        "end_at": (start + timedelta(hours=3)).isoformat(),
        "timezone": "Africa/Nairobi",
        "registration_open_at": (now - timedelta(minutes=5)).isoformat(),
        "registration_close_at": (start - timedelta(hours=1)).isoformat(),
        "capacity": 1,
    })
    assert event_response.status_code == 201, event_response.text
    event_id = event_response.json()["id"]
    assert event_response.json()["status"] == "draft"

    assert test_client.post(f"/api/v1/workspaces/{workspace_id}/events/{event_id}/publish",
                            headers=headers).status_code == 409
    ticket_response = test_client.post(
        f"/api/v1/workspaces/{workspace_id}/events/{event_id}/ticket-types",
        headers=headers,
        json={"name": "General Admission", "capacity": 1},
    )
    assert ticket_response.status_code == 201, ticket_response.text
    ticket_type_id = ticket_response.json()["id"]
    assert ticket_response.json()["price"] == "0.00"

    published = test_client.post(f"/api/v1/workspaces/{workspace_id}/events/{event_id}/publish",
                                 headers=headers)
    assert published.status_code == 200
    assert published.json()["status"] == "published"
    assert published.json()["visibility"] == "public"

    public_event = test_client.get(f"/api/v1/public/events/{event_id}")
    assert public_event.status_code == 200
    assert "registration_count" not in public_event.json()
    assert "registration_count" not in public_event.json()["ticket_types"][0]

    registration_data = {
        "full_name": "Taylor Example",
        "email": "taylor@example.com",
        "ticket_type_id": ticket_type_id,
    }
    key = str(uuid4())
    first = test_client.post(f"/api/v1/public/events/{event_id}/registrations", json=registration_data,
                             headers={"Idempotency-Key": key})
    assert first.status_code == 201, first.text
    assert first.json()["status"] == "confirmed"
    assert first.json()["ticket_credential"]

    ticket_page = test_client.post("/api/v1/public/tickets/lookup",
                                   json={"credential": first.json()["ticket_credential"]})
    assert ticket_page.status_code == 200
    assert ticket_page.json()["attendee_name"] == "Taylor Example"

    retry = test_client.post(f"/api/v1/public/events/{event_id}/registrations", json=registration_data,
                             headers={"Idempotency-Key": key})
    assert retry.status_code == 200
    assert retry.json()["confirmation_code"] == first.json()["confirmation_code"]
    assert retry.json()["ticket_credential"] == first.json()["ticket_credential"]

    duplicate_email = test_client.post(f"/api/v1/public/events/{event_id}/registrations",
                                       json=registration_data,
                                       headers={"Idempotency-Key": str(uuid4())})
    assert duplicate_email.status_code == 409

    full = test_client.post(f"/api/v1/public/events/{event_id}/registrations", json={
        **registration_data,
        "full_name": "Morgan Example",
        "email": "morgan@example.com",
    }, headers={"Idempotency-Key": str(uuid4())})
    assert full.status_code == 409
    assert test_client.get(f"/api/v1/workspaces/{workspace_id}/events/{event_id}").json()["registration_count"] == 1

    started = test_client.post(f"/api/v1/workspaces/{workspace_id}/events/{event_id}/start",
                              headers=headers)
    assert started.status_code == 200
    scan_id = str(uuid4())
    scan_payload = {"ticket_credential": first.json()["ticket_credential"], "scan_event_id": scan_id}
    checked_in = test_client.post(f"/api/v1/events/{event_id}/attendance/check-in",
                                  json=scan_payload, headers=headers)
    assert checked_in.status_code == 200
    assert checked_in.json()["duplicate"] is False
    retried = test_client.post(f"/api/v1/events/{event_id}/attendance/check-in",
                               json=scan_payload, headers=headers)
    assert retried.status_code == 200
    assert retried.json()["duplicate"] is True
    attendance = test_client.get(f"/api/v1/workspaces/{workspace_id}/events/{event_id}/attendance")
    assert attendance.status_code == 200
    assert len(attendance.json()) == 1
    revoked = test_client.post(
        f"/api/v1/workspaces/{workspace_id}/events/{event_id}/tickets/{first.json()['ticket_id']}/revoke",
        headers=headers,
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"
    assert test_client.post("/api/v1/public/tickets/lookup",
                            json={"credential": first.json()["ticket_credential"]}).status_code == 404


def test_paid_registration_stays_disabled_without_daraja_callback_configuration(client, monkeypatch):
    test_client, engine = client
    monkeypatch.setenv("PAYMENT_PROVIDER", "none")
    workspace_id, csrf = register_and_login(
        test_client, engine, "paid-organizer@example.com", "correct horse battery staple", "Paid organizer"
    )
    headers = {"X-CSRF-Token": csrf}
    now = datetime.now(timezone.utc)
    start = now + timedelta(days=3)
    event = test_client.post(f"/api/v1/workspaces/{workspace_id}/events", headers=headers, json={
        "title": "Paid Forum", "visibility": "public",
        "start_at": start.isoformat(), "end_at": (start + timedelta(hours=2)).isoformat(),
        "timezone": "Africa/Nairobi", "registration_close_at": (start - timedelta(hours=1)).isoformat(),
    })
    assert event.status_code == 201, event.text
    event_id = event.json()["id"]
    ticket = test_client.post(
        f"/api/v1/workspaces/{workspace_id}/events/{event_id}/ticket-types",
        headers=headers,
        json={"name": "Paid admission", "price": "250"},
    )
    assert ticket.status_code == 201, ticket.text
    ticket_type_id = ticket.json()["id"]
    assert test_client.post(
        f"/api/v1/workspaces/{workspace_id}/events/{event_id}/publish", headers=headers,
    ).status_code == 200

    registration = {
        "full_name": "Amani Buyer", "email": "buyer@example.com", "ticket_type_id": ticket_type_id,
    }
    idempotency_key = str(uuid4())
    rejected_free = test_client.post(
        f"/api/v1/public/events/{event_id}/registrations", json=registration,
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert rejected_free.status_code == 409
    checkout = test_client.post(
        f"/api/v1/payments/public/events/{event_id}/registrations",
        json={**registration, "phone_number": "0712345678"},
        headers={"Idempotency-Key": idempotency_key},
    )
    assert checkout.status_code == 503
    assert "not configured" in checkout.json()["detail"]
    assert test_client.get(f"/api/v1/workspaces/{workspace_id}/events/{event_id}").json()["registration_count"] == 0

    for key, value in {
        "PAYMENT_PROVIDER": "daraja", "DARAJA_ENVIRONMENT": "sandbox",
        "DARAJA_CONSUMER_KEY": "test-key", "DARAJA_CONSUMER_SECRET": "test-secret",
        "DARAJA_SHORTCODE": "174379", "DARAJA_PASSKEY": "test-passkey",
        "DARAJA_CALLBACK_BASE_URL": "https://callback.example",
    }.items():
        monkeypatch.setenv(key, value)

    class FakeDaraja:
        def __init__(self, settings):
            self.settings = settings

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def initiate_stk_push(self, **kwargs):
            assert kwargs["amount"] == Decimal("250.00")
            suffix = "failed" if kwargs["phone_number"].endswith("79") else "test_123"
            return {"CheckoutRequestID": f"ws_CO_{suffix}", "MerchantRequestID": f"merchant_{suffix}"}

        async def query_stk_push(self, *, checkout_request_id):
            if checkout_request_id == "ws_CO_failed":
                return {"ResponseCode": "0", "ResultCode": "1032", "ResultDesc": "Cancelled"}
            return {"ResponseCode": "0", "ResultCode": "0", "ResultDesc": "Success"}

    monkeypatch.setattr("app.modules.payments.routes.DarajaClient", FakeDaraja)
    started = test_client.post(
        f"/api/v1/payments/public/events/{event_id}/registrations",
        json={**registration, "phone_number": "0712345678"},
        headers={"Idempotency-Key": idempotency_key},
    )
    assert started.status_code == 202, started.text
    assert started.json()["status"] == "pending"
    assert test_client.get(f"/api/v1/workspaces/{workspace_id}/events/{event_id}").json()["registration_count"] == 1

    callback = {
        "Body": {"stkCallback": {
            "MerchantRequestID": "merchant_test_123", "CheckoutRequestID": "ws_CO_test_123",
            "ResultCode": 0, "ResultDesc": "success",
            "CallbackMetadata": {"Item": [
                {"Name": "Amount", "Value": 250},
                {"Name": "MpesaReceiptNumber", "Value": "TESTRECEIPT1"},
                {"Name": "PhoneNumber", "Value": 254712345678},
            ]},
        }},
    }
    callback_response = test_client.post("/api/v1/payments/daraja/callback", json=callback)
    assert callback_response.status_code == 200, callback_response.text
    status = test_client.get(
        f"/api/v1/payments/{started.json()['payment_id']}",
        headers={"Idempotency-Key": idempotency_key},
    )
    assert status.status_code == 200, status.text
    assert status.json()["status"] == "succeeded"
    credential = status.json()["ticket_credential"]
    assert credential
    assert test_client.post("/api/v1/public/tickets/lookup", json={"credential": credential}).status_code == 200

    csrf = test_client.cookies.get("evenspace_csrf")
    refund_key = str(uuid4())
    refund_url = f"/api/v1/workspaces/{workspace_id}/payments/{started.json()['payment_id']}/refunds"
    refund = test_client.post(
        refund_url, json={"reason": "Event cancelled"},
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": refund_key},
    )
    assert refund.status_code == 202, refund.text
    assert refund.json()["status"] == "requested"
    assert "No M-Pesa reversal has been sent" in refund.json()["message"]
    refund_list = test_client.get(refund_url, headers={"X-CSRF-Token": csrf})
    assert refund_list.status_code == 200
    assert len(refund_list.json()) == 1
    refund_retry = test_client.post(
        refund_url, json={"reason": "Event cancelled"},
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": refund_key},
    )
    assert refund_retry.status_code == 200
    excess_refund = test_client.post(
        refund_url, json={"amount": "1", "reason": "Additional refund"},
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": str(uuid4())},
    )
    assert excess_refund.status_code == 409

    duplicate_callback = test_client.post("/api/v1/payments/daraja/callback", json=callback)
    assert duplicate_callback.status_code == 200
    assert test_client.get(f"/api/v1/workspaces/{workspace_id}/events/{event_id}").json()["registration_count"] == 1

    failed_key = str(uuid4())
    failed = test_client.post(
        f"/api/v1/payments/public/events/{event_id}/registrations",
        json={**registration, "email": "cancelled@example.com", "phone_number": "0712345679"},
        headers={"Idempotency-Key": failed_key},
    )
    assert failed.status_code == 202
    failure_callback = {"Body": {"stkCallback": {
        "CheckoutRequestID": "ws_CO_failed", "MerchantRequestID": "merchant_failed",
        "ResultCode": 1032, "ResultDesc": "Cancelled by customer",
    }}}
    assert test_client.post("/api/v1/payments/daraja/callback", json=failure_callback).status_code == 200
    failed_status = test_client.get(
        f"/api/v1/payments/{failed.json()['payment_id']}",
        headers={"Idempotency-Key": failed_key},
    )
    assert failed_status.status_code == 200
    assert failed_status.json()["status"] == "failed"
    assert test_client.get(f"/api/v1/workspaces/{workspace_id}/events/{event_id}").json()["registration_count"] == 1


def test_event_management_is_workspace_scoped(client):
    test_client, engine = client
    own_workspace_id, csrf = register_and_login(
        test_client, engine, "member@example.com", "correct horse battery staple", "Member workspace"
    )

    with Session(engine) as session:
        other_user = User(email="other@example.com", password_hash="test-only")
        other_workspace = Workspace(name="Other workspace")
        session.add_all([other_user, other_workspace])
        session.flush()
        session.add(WorkspaceMembership(user_id=other_user.id, workspace_id=other_workspace.id,
                                        role=WorkspaceRole.OWNER))
        session.commit()
        other_workspace_id = other_workspace.id

    payload = {
        "title": "Private event",
        "start_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        "end_at": (datetime.now(timezone.utc) + timedelta(days=1, hours=1)).isoformat(),
        "timezone": "UTC",
    }
    own = test_client.post(f"/api/v1/workspaces/{own_workspace_id}/events", json=payload,
                           headers={"X-CSRF-Token": csrf})
    assert own.status_code == 201
    denied = test_client.post(f"/api/v1/workspaces/{other_workspace_id}/events", json=payload,
                              headers={"X-CSRF-Token": csrf})
    assert denied.status_code == 404


def test_published_private_event_is_not_publicly_visible(client):
    test_client, engine = client
    workspace_id, csrf = register_and_login(
        test_client, engine, "institution@example.com", "correct horse battery staple", "Institution"
    )
    headers = {"X-CSRF-Token": csrf}
    start = datetime.now(timezone.utc) + timedelta(days=3)
    event = test_client.post(f"/api/v1/workspaces/{workspace_id}/events", headers=headers, json={
        "title": "Internal meeting",
        "start_at": start.isoformat(),
        "end_at": (start + timedelta(hours=1)).isoformat(),
        "timezone": "Africa/Nairobi",
    }).json()
    ticket = test_client.post(
        f"/api/v1/workspaces/{workspace_id}/events/{event['id']}/ticket-types",
        headers=headers,
        json={"name": "Invitee"},
    )
    assert ticket.status_code == 201
    assert test_client.post(f"/api/v1/workspaces/{workspace_id}/events/{event['id']}/publish",
                            headers=headers).status_code == 200
    assert test_client.get(f"/api/v1/public/events/{event['id']}").status_code == 404
    registration = test_client.post(
        f"/api/v1/public/events/{event['id']}/registrations",
        json={"full_name": "Guest", "email": "guest@example.com", "ticket_type_id": ticket.json()["id"]},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert registration.status_code == 404


def test_only_an_assigned_gate_operator_can_scan(client):
    organizer_client, engine = client
    workspace_id, owner_csrf = register_and_login(
        organizer_client, engine, "gate-owner@example.com", "correct horse battery staple", "Gate team"
    )
    workspace_uuid = UUID(workspace_id)
    owner_headers = {"X-CSRF-Token": owner_csrf}
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        assigned_operator = User(
            email="assigned@example.com", password_hash=hash_password("operator test password"),
            email_verified_at=now,
        )
        unassigned_operator = User(
            email="unassigned@example.com", password_hash=hash_password("operator test password"),
            email_verified_at=now,
        )
        session.add_all([assigned_operator, unassigned_operator])
        session.flush()
        session.add_all([
            WorkspaceMembership(user_id=assigned_operator.id, workspace_id=workspace_uuid,
                                role=WorkspaceRole.MEMBER),
            WorkspaceMembership(user_id=unassigned_operator.id, workspace_id=workspace_uuid,
                                role=WorkspaceRole.MEMBER),
        ])
        assigned_id = assigned_operator.id
        session.commit()

    start = datetime.now(timezone.utc) + timedelta(days=1)
    event = organizer_client.post(f"/api/v1/workspaces/{workspace_id}/events", headers=owner_headers, json={
        "title": "Gate test",
        "visibility": "public",
        "start_at": start.isoformat(),
        "end_at": (start + timedelta(hours=2)).isoformat(),
        "timezone": "UTC",
    }).json()
    ticket_type = organizer_client.post(
        f"/api/v1/workspaces/{workspace_id}/events/{event['id']}/ticket-types",
        headers=owner_headers,
        json={"name": "Standard"},
    ).json()
    organizer_client.post(f"/api/v1/workspaces/{workspace_id}/events/{event['id']}/publish",
                          headers=owner_headers)
    participant = organizer_client.post(f"/api/v1/public/events/{event['id']}/registrations", json={
        "full_name": "Gate Guest",
        "email": "gate-guest@example.com",
        "ticket_type_id": ticket_type["id"],
    }, headers={"Idempotency-Key": str(uuid4())}).json()
    assigned = organizer_client.post(
        f"/api/v1/workspaces/{workspace_id}/events/{event['id']}/operators/{assigned_id}",
        headers=owner_headers,
    )
    assert assigned.status_code == 200
    started = organizer_client.post(f"/api/v1/workspaces/{workspace_id}/events/{event['id']}/start",
                                    headers=owner_headers)
    assert started.status_code == 200

    scan = {"ticket_credential": participant["ticket_credential"], "scan_event_id": str(uuid4())}
    operator_client = TestClient(app)
    login = operator_client.post("/api/v1/auth/login", json={
        "email": "assigned@example.com", "password": "operator test password",
    })
    assert login.status_code == 200
    operator_headers = {"X-CSRF-Token": operator_client.cookies.get("evenspace_csrf")}
    assert operator_client.post(f"/api/v1/events/{event['id']}/attendance/check-in", json=scan,
                                headers=operator_headers).status_code == 200

    unassigned_client = TestClient(app)
    login = unassigned_client.post("/api/v1/auth/login", json={
        "email": "unassigned@example.com", "password": "operator test password",
    })
    assert login.status_code == 200
    unassigned_headers = {"X-CSRF-Token": unassigned_client.cookies.get("evenspace_csrf")}
    denied = unassigned_client.post(f"/api/v1/events/{event['id']}/attendance/check-in", json=scan,
                                   headers=unassigned_headers)
    assert denied.status_code == 403


def test_offline_device_snapshot_batch_retry_and_conflict_resolution(client):
    test_client, engine = client
    workspace_id, csrf = register_and_login(
        test_client, engine, "offline-owner@example.com", "correct horse battery staple", "Offline workspace"
    )
    headers = {"X-CSRF-Token": csrf}
    start = datetime.now(timezone.utc) + timedelta(days=1)
    event = test_client.post(f"/api/v1/workspaces/{workspace_id}/events", headers=headers, json={
        "title": "Offline check-in", "visibility": "public", "start_at": start.isoformat(),
        "end_at": (start + timedelta(hours=2)).isoformat(), "timezone": "UTC",
    })
    assert event.status_code == 201, event.text
    event_id = event.json()["id"]
    ticket_type = test_client.post(
        f"/api/v1/workspaces/{workspace_id}/events/{event_id}/ticket-types",
        headers=headers, json={"name": "Admission"},
    )
    assert ticket_type.status_code == 201
    assert test_client.post(f"/api/v1/workspaces/{workspace_id}/events/{event_id}/publish",
                            headers=headers).status_code == 200

    device = test_client.post(
        f"/api/v1/workspaces/{workspace_id}/events/{event_id}/scan-devices",
        headers=headers, json={"name": "Front gate", "expires_in_days": 7},
    )
    assert device.status_code == 201, device.text
    token = device.json()["token"]
    assert token

    devices_list = test_client.get(
        f"/api/v1/workspaces/{workspace_id}/events/{event_id}/scan-devices", headers=headers,
    )
    assert devices_list.status_code == 200
    assert len(devices_list.json()) == 1
    assert devices_list.json()[0]["name"] == "Front gate"
    assert devices_list.json()[0]["is_active"] is True
    device_headers = {"X-Scan-Device-Token": token}
    manifest_response = test_client.get(
        f"/api/v1/events/{event_id}/attendance/offline-manifest", headers=device_headers,
    )
    assert manifest_response.status_code == 200, manifest_response.text
    manifest = manifest_response.json()
    assert manifest["tickets"] == []
    assert "token" not in manifest

    participant = test_client.post(f"/api/v1/public/events/{event_id}/registrations", json={
        "full_name": "Offline Guest", "email": "offline-guest@example.com",
        "ticket_type_id": ticket_type.json()["id"],
    }, headers={"Idempotency-Key": str(uuid4())})
    assert participant.status_code == 201, participant.text
    assert test_client.post(f"/api/v1/workspaces/{workspace_id}/events/{event_id}/start",
                            headers=headers).status_code == 200

    batch_id = str(uuid4())
    accepted_scan_id, unknown_scan_id = str(uuid4()), str(uuid4())
    batch = {
        "batch_id": batch_id, "snapshot_id": manifest["snapshot_id"], "scans": [
            {"scan_event_id": accepted_scan_id, "credential": participant.json()["ticket_credential"],
             "scanned_at": datetime.now(timezone.utc).isoformat()},
            {"scan_event_id": unknown_scan_id, "credential": "a" * 64,
             "scanned_at": datetime.now(timezone.utc).isoformat()},
        ],
    }
    synced = test_client.post(f"/api/v1/events/{event_id}/attendance/sync", headers=device_headers, json=batch)
    assert synced.status_code == 200, synced.text
    outcomes = synced.json()["outcomes"]
    assert [item["status"] for item in outcomes] == ["conflict", "conflict"]
    assert outcomes[0]["reason"] == "ticket_issued_after_snapshot"
    assert outcomes[1]["reason"] == "unknown_ticket"

    retried = test_client.post(f"/api/v1/events/{event_id}/attendance/sync", headers=device_headers, json=batch)
    assert retried.status_code == 200
    assert retried.json() == synced.json()
    changed_batch = {**batch, "scans": [*batch["scans"], {
        "scan_event_id": str(uuid4()), "credential": "b" * 64,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
    }]}
    changed = test_client.post(f"/api/v1/events/{event_id}/attendance/sync", headers=device_headers, json=changed_batch)
    assert changed.status_code == 409

    conflicts = test_client.get(
        f"/api/v1/workspaces/{workspace_id}/events/{event_id}/attendance/conflicts", headers=headers,
    )
    assert conflicts.status_code == 200, conflicts.text
    assert len(conflicts.json()) == 2
    conflict_by_reason = {item["reason"]: item for item in conflicts.json()}
    accepted = test_client.post(
        f"/api/v1/workspaces/{workspace_id}/events/{event_id}/attendance/conflicts/"
        f"{conflict_by_reason['ticket_issued_after_snapshot']['id']}/resolve",
        headers=headers, json={"action": "accept", "note": "Verified current registration"},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted"
    ignored = test_client.post(
        f"/api/v1/workspaces/{workspace_id}/events/{event_id}/attendance/conflicts/"
        f"{conflict_by_reason['unknown_ticket']['id']}/resolve",
        headers=headers, json={"action": "ignore", "note": "Credential not recognized"},
    )
    assert ignored.status_code == 200, ignored.text
    assert ignored.json()["status"] == "ignored"

    attendance = test_client.get(
        f"/api/v1/workspaces/{workspace_id}/events/{event_id}/attendance", headers=headers,
    )
    assert attendance.status_code == 200
    assert len(attendance.json()) == 1
    assert attendance.json()[0]["ticket_id"] == participant.json()["ticket_id"]


def test_offline_device_token_is_event_scoped_and_revocable(client):
    test_client, engine = client
    workspace_id, csrf = register_and_login(
        test_client, engine, "device-owner@example.com", "correct horse battery staple", "Device workspace"
    )
    headers = {"X-CSRF-Token": csrf}
    start = datetime.now(timezone.utc) + timedelta(days=1)
    event_ids = []
    for title in ("Scanner A", "Scanner B"):
        event = test_client.post(f"/api/v1/workspaces/{workspace_id}/events", headers=headers, json={
            "title": title, "start_at": start.isoformat(),
            "end_at": (start + timedelta(hours=1)).isoformat(), "timezone": "UTC",
        })
        assert event.status_code == 201
        event_ids.append(event.json()["id"])
    event_id, other_event_id = event_ids
    created = test_client.post(
        f"/api/v1/workspaces/{workspace_id}/events/{event_id}/scan-devices",
        headers=headers, json={"name": "Authorized scanner"},
    )
    assert created.status_code == 201, created.text
    token = created.json()["token"]
    wrong_scope = test_client.get(
        f"/api/v1/events/{other_event_id}/attendance/offline-manifest",
        headers={"X-Scan-Device-Token": token},
    )
    assert wrong_scope.status_code == 401
    revoked = test_client.delete(
        f"/api/v1/workspaces/{workspace_id}/events/{event_id}/scan-devices/{created.json()['id']}",
        headers=headers,
    )
    assert revoked.status_code == 204
    denied = test_client.get(
        f"/api/v1/events/{event_id}/attendance/offline-manifest",
        headers={"X-Scan-Device-Token": token},
    )
    assert denied.status_code == 401


def test_manual_check_in_by_event_manager(client):
    test_client, engine = client
    workspace_id, csrf = register_and_login(
        test_client, engine, "manual-owner@example.com", "correct horse battery staple", "Manual workspace"
    )
    headers = {"X-CSRF-Token": csrf}
    start = datetime.now(timezone.utc) + timedelta(days=1)
    event = test_client.post(f"/api/v1/workspaces/{workspace_id}/events", headers=headers, json={
        "title": "Manual desk event", "visibility": "public", "start_at": start.isoformat(),
        "end_at": (start + timedelta(hours=2)).isoformat(), "timezone": "UTC",
    })
    assert event.status_code == 201
    event_id = event.json()["id"]

    ticket_type = test_client.post(
        f"/api/v1/workspaces/{workspace_id}/events/{event_id}/ticket-types",
        headers=headers, json={"name": "Desk pass"},
    )
    assert ticket_type.status_code == 201

    assert test_client.post(f"/api/v1/workspaces/{workspace_id}/events/{event_id}/publish", headers=headers).status_code == 200

    registered = test_client.post(f"/api/v1/public/events/{event_id}/registrations", json={
        "full_name": "Walk-in Guest", "email": "walkin@example.com",
        "ticket_type_id": ticket_type.json()["id"],
    }, headers={"Idempotency-Key": str(uuid4())})
    assert registered.status_code == 201
    registration_id = registered.json()["id"]

    assert test_client.post(f"/api/v1/workspaces/{workspace_id}/events/{event_id}/start", headers=headers).status_code == 200

    # Manual check-in from organizer console
    check_in = test_client.post(
        f"/api/v1/workspaces/{workspace_id}/events/{event_id}/registrations/{registration_id}/manual-check-in",
        headers=headers,
    )
    assert check_in.status_code == 200
    assert check_in.json()["attendee_name"] == "Walk-in Guest"
    assert check_in.json()["event_type"] == "check_in"

    # Repeated manual check-in is idempotent
    second = test_client.post(
        f"/api/v1/workspaces/{workspace_id}/events/{event_id}/registrations/{registration_id}/manual-check-in",
        headers=headers,
    )
    assert second.status_code == 200
    assert second.json()["attendance_event_id"] == check_in.json()["attendance_event_id"]

    # Registrations list reflects checked in timestamp
    registrations = test_client.get(f"/api/v1/workspaces/{workspace_id}/events/{event_id}/registrations", headers=headers)
    assert registrations.status_code == 200
    reg_record = next(r for r in registrations.json() if r["id"] == registration_id)
    assert reg_record["checked_in_at"] is not None


def test_public_meeting_guest_registration_normalizes_email_and_is_idempotent(client):
    test_client, engine = client
    workspace_id, csrf = register_and_login(
        test_client, engine, "meeting-owner@example.com", "correct horse battery staple", "Meeting Workspace"
    )
    headers = {"X-CSRF-Token": csrf}
    start = datetime.now(timezone.utc) + timedelta(days=2)
    scheduled = test_client.post(f"/api/v1/workspaces/{workspace_id}/meetings/schedule", headers=headers, json={
        "title": "Public registration test",
        "meeting_type": "Community meeting",
        "start_at": start.isoformat(),
        "end_at": (start + timedelta(hours=1)).isoformat(),
        "timezone": "Africa/Nairobi",
        "meeting_mode": "physical",
        "online_url": None,
    })
    assert scheduled.status_code == 201, scheduled.text
    meeting_id = scheduled.json()["id"]

    join_link = test_client.post(
        f"/api/v1/workspaces/{workspace_id}/meetings/{meeting_id}/join-link", headers=headers,
    )
    assert join_link.status_code == 200, join_link.text
    token = join_link.json()["token"]
    join_url = f"/api/v1/public/meetings/{meeting_id}/join"
    signature_data, signature_png = signature_data_url()
    captured_at = datetime.now(timezone.utc).isoformat()
    registration = {
        "token": token,
        "full_name": "Taylor Example",
        "email": "Taylor.Example@Example.com",
        "phone": "+254 712 345 678",
        "attendee_type": "guest",
        "organization": "Example Group",
        "signature_data": signature_data,
        "gps_latitude": -1.2864,
        "gps_longitude": 36.8172,
        "gps_accuracy_m": 18.5,
        "gps_captured_at": captured_at,
    }

    first = test_client.post(join_url, json=registration)
    assert first.status_code == 201, first.text
    assert first.json()["registration"]["email"] == "taylor.example@example.com"
    assert first.json()["registration"]["phone"] == "+254712345678"
    assert "gps_latitude" not in first.json()["registration"]
    assert "signature_present" not in first.json()["registration"]

    retry = test_client.post(join_url, json=registration)
    assert retry.status_code == 200, retry.text
    assert retry.json()["registration"]["id"] == first.json()["registration"]["id"]

    with Session(engine) as session:
        rows = session.scalars(select(MeetingGuestRegistration).where(
            MeetingGuestRegistration.meeting_id == UUID(meeting_id),
        )).all()
    assert len(rows) == 1
    assert rows[0].signature_png == signature_png
    assert rows[0].gps_latitude == -1.2864
    assert rows[0].gps_longitude == 36.8172
    assert rows[0].gps_accuracy_m == 18.5
    assert rows[0].gps_captured_at is not None

    organizer_rows = test_client.get(
        f"/api/v1/workspaces/{workspace_id}/meetings/{meeting_id}/guest-registrations", headers=headers,
    )
    assert organizer_rows.status_code == 200, organizer_rows.text
    organizer_attendee = organizer_rows.json()[0]
    assert organizer_attendee["signature_present"] is True
    assert organizer_attendee["gps_latitude"] == -1.2864
    assert organizer_attendee["registration_source"] == "qr"
    assert "signature_png" not in organizer_attendee
    signature_response = test_client.get(
        f"/api/v1/workspaces/{workspace_id}/meetings/{meeting_id}/guest-registrations/{organizer_attendee['id']}/signature",
        headers=headers,
    )
    assert signature_response.status_code == 200
    assert signature_response.headers["content-type"] == "image/png"
    assert signature_response.content == signature_png
    with TestClient(app) as anonymous_client:
        unauthorized_signature = anonymous_client.get(
            f"/api/v1/workspaces/{workspace_id}/meetings/{meeting_id}/guest-registrations/{organizer_attendee['id']}/signature",
        )
    assert unauthorized_signature.status_code == 401

    manual_url = f"/api/v1/workspaces/{workspace_id}/meetings/{meeting_id}/guest-registrations"
    manual_attendee = {
        "full_name": "Jordan Speaker", "email": "jordan.speaker@example.com", "phone": "+254700111222",
        "attendee_type": "speaker", "organization": "Example Association",
    }
    assert test_client.post(manual_url, json=manual_attendee).status_code == 403
    manual_result = test_client.post(manual_url, json=manual_attendee, headers=headers)
    assert manual_result.status_code == 201, manual_result.text
    assert manual_result.json()["attendee_type"] == "speaker"
    assert manual_result.json()["registration_source"] == "admin"
    assert manual_result.json()["registered_by_id"] is not None
    assert manual_result.json()["signature_present"] is False
    assert manual_result.json()["gps_latitude"] is None
    assert test_client.post(manual_url, json=manual_attendee, headers=headers).status_code == 409

    missing_signature = {key: value for key, value in registration.items() if key != "signature_data"}
    missing_signature["email"] = "without-signature@example.com"
    assert test_client.post(join_url, json=missing_signature).status_code == 422
    malformed_signature = {**registration, "email": "bad-signature@example.com", "signature_data": "data:image/png;base64,not-a-png"}
    assert test_client.post(join_url, json=malformed_signature).status_code == 422
    empty_signature = {**registration, "email": "empty-signature@example.com", "signature_data": " "}
    assert test_client.post(join_url, json=empty_signature).status_code == 422
    oversized_signature = {**registration, "email": "large-signature@example.com", "signature_data": "x" * 131073}
    assert test_client.post(join_url, json=oversized_signature).status_code == 422
    invalid_location = {**registration, "email": "bad-location@example.com", "gps_latitude": 91}
    assert test_client.post(join_url, json=invalid_location).status_code == 422
    unpaired_location = {**registration, "email": "unpaired-location@example.com"}
    del unpaired_location["gps_longitude"]
    assert test_client.post(join_url, json=unpaired_location).status_code == 422

    no_location = {key: value for key, value in registration.items() if not key.startswith("gps_")}
    no_location["email"] = "no-location@example.com"
    no_location_result = test_client.post(join_url, json=no_location)
    assert no_location_result.status_code == 201, no_location_result.text
    assert "gps_latitude" not in no_location_result.json()["registration"]

    privacy_url = f"/api/v1/workspaces/{workspace_id}/meetings/{meeting_id}/guest-registrations/{organizer_attendee['id']}/privacy-data"
    assert test_client.delete(privacy_url).status_code == 403
    erased = test_client.delete(privacy_url, headers=headers)
    assert erased.status_code == 200, erased.text
    assert erased.json()["signature_present"] is False
    assert erased.json()["gps_latitude"] is None
    assert test_client.get(
        f"/api/v1/workspaces/{workspace_id}/meetings/{meeting_id}/guest-registrations/{organizer_attendee['id']}/signature",
        headers=headers,
    ).status_code == 404
