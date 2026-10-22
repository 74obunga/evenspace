"""Issue QR-ready tickets and record online attendance.

Revision ID: 0004_tickets_attendance
Revises: 0003_events_registration
Create Date: 2026-10-20
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_tickets_attendance"
down_revision = "0003_events_registration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE event_status ADD VALUE IF NOT EXISTS 'IN_PROGRESS'")
    ticket_status = sa.Enum("ACTIVE", "REVOKED", name="ticket_status")
    attendance_type = sa.Enum("CHECK_IN", name="attendance_event_type")

    op.create_table(
        "tickets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("registration_id", sa.Uuid(), nullable=False),
        sa.Column("ticket_type_id", sa.Uuid(), nullable=False),
        sa.Column("credential_hash", sa.String(length=64), nullable=False),
        sa.Column("status", ticket_status, nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["registration_id"], ["registrations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["ticket_type_id"], ["ticket_types.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tickets_event_id", "tickets", ["event_id"])
    op.create_index("ix_tickets_registration_id", "tickets", ["registration_id"], unique=True)
    op.create_index("ix_tickets_ticket_type_id", "tickets", ["ticket_type_id"])
    op.create_index("ix_tickets_credential_hash", "tickets", ["credential_hash"], unique=True)

    op.create_table(
        "event_operator_assignments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_by_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["assigned_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "user_id", name="uq_event_operator_user"),
    )
    op.create_index("ix_event_operator_assignments_event_id", "event_operator_assignments", ["event_id"])
    op.create_index("ix_event_operator_assignments_user_id", "event_operator_assignments", ["user_id"])

    op.create_table(
        "attendance_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", attendance_type, nullable=False),
        sa.Column("scan_event_id", sa.Uuid(), nullable=False),
        sa.Column("recorded_by_id", sa.Uuid(), nullable=False),
        sa.Column("scanned_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["recorded_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "ticket_id", "event_type", name="uq_attendance_event_ticket_type"),
        sa.UniqueConstraint("scan_event_id", name="uq_attendance_scan_event_id"),
    )
    op.create_index("ix_attendance_events_event_id", "attendance_events", ["event_id"])
    op.create_index("ix_attendance_events_ticket_id", "attendance_events", ["ticket_id"])


def downgrade() -> None:
    op.drop_index("ix_attendance_events_ticket_id", table_name="attendance_events")
    op.drop_index("ix_attendance_events_event_id", table_name="attendance_events")
    op.drop_table("attendance_events")
    op.drop_index("ix_event_operator_assignments_user_id", table_name="event_operator_assignments")
    op.drop_index("ix_event_operator_assignments_event_id", table_name="event_operator_assignments")
    op.drop_table("event_operator_assignments")
    op.drop_index("ix_tickets_credential_hash", table_name="tickets")
    op.drop_index("ix_tickets_ticket_type_id", table_name="tickets")
    op.drop_index("ix_tickets_registration_id", table_name="tickets")
    op.drop_index("ix_tickets_event_id", table_name="tickets")
    op.drop_table("tickets")
    sa.Enum(name="attendance_event_type").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="ticket_status").drop(op.get_bind(), checkfirst=True)
