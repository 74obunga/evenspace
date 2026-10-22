"""Persist the exact tickets included in each offline snapshot.

Revision ID: 0006_snapshot_ticket_membership
Revises: 0005_offline_sync
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_snapshot_ticket_membership"
down_revision = "0005_offline_sync"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("scan_device_snapshot_tickets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=False),
        sa.Column("credential_hash", sa.String(64), nullable=False),
        sa.Column("ticket_status", sa.String(16), nullable=False),
        sa.Column("attendee_name", sa.String(200), nullable=False),
        sa.ForeignKeyConstraint(["snapshot_id"], ["scan_device_snapshots.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", "ticket_id", name="uq_snapshot_ticket"))
    op.create_index("ix_scan_device_snapshot_tickets_snapshot_id", "scan_device_snapshot_tickets", ["snapshot_id"])
    op.create_index("ix_scan_device_snapshot_tickets_ticket_id", "scan_device_snapshot_tickets", ["ticket_id"])


def downgrade() -> None:
    op.drop_index("ix_scan_device_snapshot_tickets_ticket_id", table_name="scan_device_snapshot_tickets")
    op.drop_index("ix_scan_device_snapshot_tickets_snapshot_id", table_name="scan_device_snapshot_tickets")
    op.drop_table("scan_device_snapshot_tickets")
