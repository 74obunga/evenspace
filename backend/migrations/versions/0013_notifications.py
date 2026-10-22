"""Add notification templates, outbox, and delivery attempts."""
from alembic import op
import sqlalchemy as sa
from uuid import UUID

revision = "0013_notifications"
down_revision = "0012_meeting_attachments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("key", sa.String(80), nullable=False),
        sa.Column("channel", sa.String(16), server_default="email", nullable=False),
        sa.Column("subject_template", sa.String(300), nullable=False),
        sa.Column("body_template", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("updated_by_id", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("channel IN ('email')", name="ck_notification_template_channel"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("workspace_id", "key", name="uq_notification_template_workspace_key"),
    )
    op.create_index("ix_notification_templates_workspace_id", "notification_templates", ["workspace_id"])
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(80), nullable=False),
        sa.Column("recipient_email", sa.String(320), nullable=False),
        sa.Column("template_key", sa.String(80), nullable=False),
        sa.Column("template_context", sa.JSON(), nullable=False),
        sa.Column("dedupe_key", sa.String(200), nullable=True),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("retry_generation", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_error", sa.String(1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('pending','sent','failed')", name="ck_notification_status"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("dedupe_key", name="uq_notification_dedupe_key"),
    )
    op.create_index("ix_notifications_kind", "notifications", ["kind"])
    op.create_index("ix_notifications_workspace_id", "notifications", ["workspace_id"])
    op.create_index("ix_notifications_delivery", "notifications", ["status", "next_attempt_at", "created_at"])
    op.create_table(
        "notification_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("notification_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error", sa.String(1000), nullable=True),
        sa.Column("attempted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('sent','failed')", name="ck_notification_attempt_status"),
        sa.ForeignKeyConstraint(["notification_id"], ["notifications.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("notification_id", "attempt_number", name="uq_notification_attempt_number"),
    )
    op.create_index("ix_notification_attempts_notification_id", "notification_attempts", ["notification_id"])
    op.bulk_insert(
        sa.table("notification_templates",
                 sa.column("id", sa.Uuid()), sa.column("workspace_id", sa.Uuid()), sa.column("key", sa.String()),
                 sa.column("channel", sa.String()), sa.column("subject_template", sa.String()),
                 sa.column("body_template", sa.Text()), sa.column("enabled", sa.Boolean())),
        [
            {"id": UUID("10000000-0000-0000-0000-000000000001"), "key": "registration_confirmation", "channel": "email", "subject_template": "Registration confirmed: {event_title}", "body_template": "Hello {full_name},\n\nYour registration for {event_title} is confirmed.\n\nEvent starts: {event_start}\n\nEvenSpace", "enabled": True},
            {"id": UUID("10000000-0000-0000-0000-000000000002"), "key": "meeting_invitation", "channel": "email", "subject_template": "Meeting invitation: {meeting_type}", "body_template": "Hello {full_name},\n\nYou have been invited to {meeting_type}.\nEvent: {event_title}\nStarts: {event_start}\n\nOpen EvenSpace to view the meeting record.", "enabled": True},
            {"id": UUID("10000000-0000-0000-0000-000000000003"), "key": "payment_confirmation", "channel": "email", "subject_template": "Payment confirmed: {event_title}", "body_template": "Hello {full_name},\n\nYour payment for {event_title} has been confirmed.\nEvent starts: {event_start}\n\nEvenSpace", "enabled": True},
            {"id": UUID("10000000-0000-0000-0000-000000000004"), "key": "refund_update", "channel": "email", "subject_template": "Refund update: {event_title}", "body_template": "Hello {full_name},\n\nYour refund request for {event_title} is now {refund_status}.\n\nEvenSpace", "enabled": True},
            {"id": UUID("10000000-0000-0000-0000-000000000005"), "key": "event_reminder", "channel": "email", "subject_template": "Reminder: {event_title}", "body_template": "Hello {full_name},\n\nThis is a reminder that {event_title} starts at {event_start}.\n\nEvenSpace", "enabled": True},
            {"id": UUID("10000000-0000-0000-0000-000000000006"), "key": "event_update", "channel": "email", "subject_template": "Event update: {event_title}", "body_template": "Hello {full_name},\n\nThere is an update to {event_title}:\n{change_summary}\n\nEvenSpace", "enabled": True},
            {"id": UUID("10000000-0000-0000-0000-000000000007"), "key": "event_cancellation", "channel": "email", "subject_template": "Event cancelled: {event_title}", "body_template": "Hello {full_name},\n\n{event_title} has been cancelled.\nReason: {reason}\n\nEvenSpace", "enabled": True},
            {"id": UUID("10000000-0000-0000-0000-000000000008"), "key": "organizer_alert", "channel": "email", "subject_template": "EvenSpace organizer alert: {event_title}", "body_template": "{alert_message}\n\nEvenSpace", "enabled": True},
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_notification_attempts_notification_id", table_name="notification_attempts")
    op.drop_table("notification_attempts")
    op.drop_index("ix_notifications_delivery", table_name="notifications")
    op.drop_index("ix_notifications_workspace_id", table_name="notifications")
    op.drop_index("ix_notifications_kind", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("ix_notification_templates_workspace_id", table_name="notification_templates")
    op.drop_table("notification_templates")
