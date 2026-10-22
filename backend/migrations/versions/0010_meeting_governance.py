"""Add institutional meeting agendas, minutes, decisions, and actions.

Revision ID: 0010_meeting_governance
Revises: 0009_refund_requests
"""
from alembic import op
import sqlalchemy as sa

revision = "0010_meeting_governance"
down_revision = "0009_refund_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("meetings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("meeting_type", sa.String(80), nullable=False),
        sa.Column("chairperson_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(16), server_default="draft", nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('draft','scheduled','held','cancelled')", name="ck_meeting_status"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["chairperson_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("event_id", name="uq_meeting_event"))
    op.create_index("ix_meetings_workspace_id", "meetings", ["workspace_id"])
    op.create_index("ix_meetings_event_id", "meetings", ["event_id"])

    op.create_table("meeting_agenda_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("presenter_id", sa.Uuid(), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("position > 0", name="ck_meeting_agenda_position_positive"),
        sa.CheckConstraint("duration_minutes IS NULL OR duration_minutes > 0", name="ck_meeting_agenda_duration_positive"),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["presenter_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("meeting_id", "position", name="uq_meeting_agenda_position"))
    op.create_index("ix_meeting_agenda_items_meeting_id", "meeting_agenda_items", ["meeting_id"])

    op.create_table("meeting_minutes_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), server_default="draft", nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by_id", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approval_note", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("revision > 0", name="ck_meeting_minutes_revision_positive"),
        sa.CheckConstraint("status IN ('draft','submitted','approved','rejected')", name="ck_meeting_minutes_status"),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["approved_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("meeting_id", "revision", name="uq_meeting_minutes_revision"))
    op.create_index("ix_meeting_minutes_revisions_meeting_id", "meeting_minutes_revisions", ["meeting_id"])
    op.create_index("ix_meeting_minutes_status", "meeting_minutes_revisions", ["meeting_id", "status"])

    op.create_table("meeting_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
        sa.Column("decision_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), server_default="proposed", nullable=False),
        sa.Column("proposed_by_id", sa.Uuid(), nullable=False),
        sa.Column("resolved_by_id", sa.Uuid(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("decision_number > 0", name="ck_meeting_decision_number_positive"),
        sa.CheckConstraint("status IN ('proposed','adopted','rejected')", name="ck_meeting_decision_status"),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["proposed_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["resolved_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("meeting_id", "decision_number", name="uq_meeting_decision_number"))
    op.create_index("ix_meeting_decisions_meeting_id", "meeting_decisions", ["meeting_id"])
    op.create_index("ix_meeting_decisions_meeting_status", "meeting_decisions", ["meeting_id", "status"])

    op.create_table("meeting_action_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
        sa.Column("decision_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("assigned_to_id", sa.Uuid(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(16), server_default="open", nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('open','in_progress','completed','cancelled')", name="ck_meeting_action_status"),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["decision_id"], ["meeting_decisions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["assigned_to_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_meeting_action_items_meeting_id", "meeting_action_items", ["meeting_id"])
    op.create_index("ix_meeting_action_items_meeting_status", "meeting_action_items", ["meeting_id", "status"])
    op.create_index("ix_meeting_action_items_assignee_due", "meeting_action_items", ["assigned_to_id", "due_at"])

    op.create_table("meeting_action_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("action_item_id", sa.Uuid(), nullable=False),
        sa.Column("from_status", sa.String(16), nullable=True),
        sa.Column("to_status", sa.String(16), nullable=False),
        sa.Column("changed_by_id", sa.Uuid(), nullable=False),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("to_status IN ('open','in_progress','completed','cancelled')", name="ck_meeting_action_history_status"),
        sa.ForeignKeyConstraint(["action_item_id"], ["meeting_action_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["changed_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_meeting_action_history_action_item_id", "meeting_action_history", ["action_item_id"])
    op.create_index("ix_meeting_action_history_item_time", "meeting_action_history", ["action_item_id", "changed_at"])


def downgrade() -> None:
    op.drop_index("ix_meeting_action_history_item_time", table_name="meeting_action_history")
    op.drop_index("ix_meeting_action_history_action_item_id", table_name="meeting_action_history")
    op.drop_table("meeting_action_history")
    op.drop_index("ix_meeting_action_items_assignee_due", table_name="meeting_action_items")
    op.drop_index("ix_meeting_action_items_meeting_status", table_name="meeting_action_items")
    op.drop_index("ix_meeting_action_items_meeting_id", table_name="meeting_action_items")
    op.drop_table("meeting_action_items")
    op.drop_index("ix_meeting_decisions_meeting_status", table_name="meeting_decisions")
    op.drop_index("ix_meeting_decisions_meeting_id", table_name="meeting_decisions")
    op.drop_table("meeting_decisions")
    op.drop_index("ix_meeting_minutes_status", table_name="meeting_minutes_revisions")
    op.drop_index("ix_meeting_minutes_revisions_meeting_id", table_name="meeting_minutes_revisions")
    op.drop_table("meeting_minutes_revisions")
    op.drop_index("ix_meeting_agenda_items_meeting_id", table_name="meeting_agenda_items")
    op.drop_table("meeting_agenda_items")
    op.drop_index("ix_meetings_event_id", table_name="meetings")
    op.drop_index("ix_meetings_workspace_id", table_name="meetings")
    op.drop_table("meetings")
