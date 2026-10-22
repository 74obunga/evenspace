"""Add expiring account password reset tokens and email template."""
from alembic import op
import sqlalchemy as sa
from uuid import UUID

revision = "0018_password_recovery"
down_revision = "0017_online_meeting_link"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"])
    op.create_index("ix_password_reset_tokens_token_hash", "password_reset_tokens", ["token_hash"], unique=True)
    op.create_index("ix_password_reset_tokens_expires_at", "password_reset_tokens", ["expires_at"])
    op.bulk_insert(
        sa.table(
            "notification_templates",
            sa.column("id", sa.Uuid()), sa.column("workspace_id", sa.Uuid()),
            sa.column("key", sa.String()), sa.column("channel", sa.String()),
            sa.column("subject_template", sa.String()), sa.column("body_template", sa.Text()),
            sa.column("enabled", sa.Boolean()),
        ),
        [{
            "id": UUID("10000000-0000-0000-0000-00000000000a"), "workspace_id": None,
            "key": "password_reset", "channel": "email",
            "subject_template": "Reset your EvenSpace password",
            "body_template": "Use this link to reset your password. The link expires in 30 minutes and can only be used once:\n\n{reset_url}\n\nIf you did not request this change, you can ignore this email.",
            "enabled": True,
        }],
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM notification_templates WHERE workspace_id IS NULL AND key = 'password_reset'"))
    op.drop_index("ix_password_reset_tokens_expires_at", table_name="password_reset_tokens")
    op.drop_index("ix_password_reset_tokens_token_hash", table_name="password_reset_tokens")
    op.drop_index("ix_password_reset_tokens_user_id", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")
