"""Encrypt ticket credentials in the notification outbox and seed ticket email."""
from uuid import UUID

from alembic import op
import sqlalchemy as sa

revision = "0015_ticket_email_secrets"
down_revision = "0014_cancel_notification_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("secret_context_ciphertext", sa.Text(), nullable=True))
    templates = sa.table(
        "notification_templates",
        sa.column("id", sa.Uuid()), sa.column("workspace_id", sa.Uuid()),
        sa.column("key", sa.String()), sa.column("channel", sa.String()),
        sa.column("subject_template", sa.String()), sa.column("body_template", sa.Text()),
        sa.column("enabled", sa.Boolean()),
    )
    op.bulk_insert(templates, [{
        "id": UUID("10000000-0000-0000-0000-000000000009"), "workspace_id": None,
        "key": "ticket_issuance", "channel": "email",
        "subject_template": "Your ticket for {event_title}",
        "body_template": "Hello {full_name},\n\nYour ticket for {event_title} is confirmed.\nEvent starts: {event_start}\n\nTicket credential: {ticket_credential}\nKeep this credential private; it is used for check-in.\n\nEvenSpace",
        "enabled": True,
    }])


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM notification_templates WHERE workspace_id IS NULL AND key='ticket_issuance'"))
    op.drop_column("notifications", "secret_context_ciphertext")
