"""Add event, free ticket type, and participant registration tables.

Revision ID: 0003_events_registration
Revises: 0002_auth_sessions
Create Date: 2026-10-19
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_events_registration"
down_revision = "0002_auth_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    event_status = sa.Enum("DRAFT", "PUBLISHED", "CANCELLED", "COMPLETED", name="event_status")
    event_visibility = sa.Enum("PUBLIC", "PRIVATE", name="event_visibility")
    registration_status = sa.Enum("CONFIRMED", "CANCELLED", name="registration_status")
    op.create_table(
        "events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("status", event_status, nullable=False),
        sa.Column("visibility", event_visibility, server_default="PRIVATE", nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.String(length=80), nullable=False),
        sa.Column("registration_open_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("registration_close_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("capacity", sa.Integer(), nullable=True),
        sa.Column("registration_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("capacity IS NULL OR capacity > 0", name="ck_event_capacity_positive"),
        sa.CheckConstraint("registration_count >= 0", name="ck_event_registration_count_nonnegative"),
        sa.CheckConstraint("end_at > start_at", name="ck_event_end_after_start"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_events_workspace_id", "events", ["workspace_id"])
    op.create_index("ix_events_created_by_id", "events", ["created_by_id"])
    op.create_table(
        "ticket_types",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price", sa.Numeric(12, 2), server_default="0", nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=True),
        sa.Column("registration_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.CheckConstraint("price >= 0", name="ck_ticket_type_price_nonnegative"),
        sa.CheckConstraint("capacity IS NULL OR capacity > 0", name="ck_ticket_type_capacity_positive"),
        sa.CheckConstraint("registration_count >= 0", name="ck_ticket_type_registration_count_nonnegative"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "name", name="uq_ticket_type_event_name"),
    )
    op.create_index("ix_ticket_types_event_id", "ticket_types", ["event_id"])
    op.create_table(
        "registrations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("ticket_type_id", sa.Uuid(), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("idempotency_key_hash", sa.String(length=64), nullable=False),
        sa.Column("status", registration_status, nullable=False),
        sa.Column("confirmation_code", sa.String(length=48), nullable=False),
        sa.Column("registered_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["ticket_type_id"], ["ticket_types.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "email", name="uq_registration_event_email"),
        sa.UniqueConstraint("event_id", "idempotency_key_hash", name="uq_registration_event_idempotency_key"),
    )
    op.create_index("ix_registrations_event_id", "registrations", ["event_id"])
    op.create_index("ix_registrations_ticket_type_id", "registrations", ["ticket_type_id"])
    op.create_index("ix_registrations_confirmation_code", "registrations", ["confirmation_code"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_registrations_confirmation_code", table_name="registrations")
    op.drop_index("ix_registrations_ticket_type_id", table_name="registrations")
    op.drop_index("ix_registrations_event_id", table_name="registrations")
    op.drop_table("registrations")
    op.drop_index("ix_ticket_types_event_id", table_name="ticket_types")
    op.drop_table("ticket_types")
    op.drop_index("ix_events_created_by_id", table_name="events")
    op.drop_index("ix_events_workspace_id", table_name="events")
    op.drop_table("events")
    sa.Enum(name="registration_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="event_visibility").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="event_status").drop(op.get_bind(), checkfirst=True)
