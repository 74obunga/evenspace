"""Add event-scoped offline scan devices, snapshots, batches and conflicts.

Revision ID: 0005_offline_sync
Revises: 0004_tickets_attendance
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_offline_sync"
down_revision = "0004_tickets_attendance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("attendance_events", sa.Column("source", sa.String(16), server_default="online", nullable=False))
    op.add_column("attendance_events", sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    conflict_status = sa.Enum("PENDING", "ACCEPTED", "IGNORED", name="offline_conflict_status")
    op.create_table("scan_devices",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False), sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="RESTRICT"), sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_scan_devices_event_id", "scan_devices", ["event_id"])
    op.create_index("ix_scan_devices_token_hash", "scan_devices", ["token_hash"], unique=True)
    op.create_index("ix_scan_devices_expires_at", "scan_devices", ["expires_at"])
    op.create_table("scan_device_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["scan_devices.id"], ondelete="RESTRICT"), sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_scan_device_snapshots_device_id", "scan_device_snapshots", ["device_id"])
    op.create_table("sync_batches",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False), sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False), sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["scan_devices.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["scan_device_snapshots.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("device_id", "batch_id", name="uq_sync_batch_device_batch"))
    op.create_index("ix_sync_batches_device_id", "sync_batches", ["device_id"])
    op.create_table("offline_scan_conflicts",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False), sa.Column("sync_batch_id", sa.Uuid(), nullable=False),
        sa.Column("scan_event_id", sa.Uuid(), nullable=False), sa.Column("ticket_id", sa.Uuid()),
        sa.Column("credential_hash", sa.String(64), nullable=False), sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(80), nullable=False), sa.Column("status", conflict_status, nullable=False),
        sa.Column("resolution_note", sa.String(500)), sa.Column("resolved_by_id", sa.Uuid()),
        sa.Column("resolved_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["device_id"], ["scan_devices.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sync_batch_id"], ["sync_batches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["resolved_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("scan_event_id", name="uq_offline_conflict_scan_event_id"))
    for col in ("event_id", "device_id", "sync_batch_id"):
        op.create_index(f"ix_offline_scan_conflicts_{col}", "offline_scan_conflicts", [col])


def downgrade() -> None:
    for col in ("sync_batch_id", "device_id", "event_id"):
        op.drop_index(f"ix_offline_scan_conflicts_{col}", table_name="offline_scan_conflicts")
    op.drop_table("offline_scan_conflicts")
    op.drop_index("ix_sync_batches_device_id", table_name="sync_batches")
    op.drop_table("sync_batches")
    op.drop_index("ix_scan_device_snapshots_device_id", table_name="scan_device_snapshots")
    op.drop_table("scan_device_snapshots")
    op.drop_index("ix_scan_devices_expires_at", table_name="scan_devices")
    op.drop_index("ix_scan_devices_token_hash", table_name="scan_devices")
    op.drop_index("ix_scan_devices_event_id", table_name="scan_devices")
    op.drop_table("scan_devices")
    op.drop_column("attendance_events", "received_at")
    op.drop_column("attendance_events", "source")
    sa.Enum(name="offline_conflict_status").drop(op.get_bind(), checkfirst=True)
