"""Require email verification for newly created accounts."""
from alembic import op
import sqlalchemy as sa
from uuid import UUID

revision = "0019_email_verification"
down_revision = "0018_password_recovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(sa.text("UPDATE users SET email_verified_at = created_at WHERE email_verified_at IS NULL"))
    op.create_table(
        "email_verification_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_email_verification_tokens_user_id", "email_verification_tokens", ["user_id"])
    op.create_index("ix_email_verification_tokens_token_hash", "email_verification_tokens", ["token_hash"], unique=True)
    op.create_index("ix_email_verification_tokens_expires_at", "email_verification_tokens", ["expires_at"])
    op.bulk_insert(
        sa.table(
            "notification_templates",
            sa.column("id", sa.Uuid()), sa.column("workspace_id", sa.Uuid()),
            sa.column("key", sa.String()), sa.column("channel", sa.String()),
            sa.column("subject_template", sa.String()), sa.column("body_template", sa.Text()),
            sa.column("enabled", sa.Boolean()),
        ),
        [{
            "id": UUID("10000000-0000-0000-0000-00000000000b"), "workspace_id": None,
            "key": "email_verification", "channel": "email",
            "subject_template": "Verify your EvenSpace email",
            "body_template": "Welcome to EvenSpace. Confirm your email address using this link within 24 hours:\n\n{verification_url}\n\nIf you did not create this account, you can ignore this email.",
            "enabled": True,
        }],
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM notification_templates WHERE workspace_id IS NULL AND key = 'email_verification'"))
    op.drop_index("ix_email_verification_tokens_expires_at", table_name="email_verification_tokens")
    op.drop_index("ix_email_verification_tokens_token_hash", table_name="email_verification_tokens")
    op.drop_index("ix_email_verification_tokens_user_id", table_name="email_verification_tokens")
    op.drop_table("email_verification_tokens")
    op.drop_column("users", "email_verified_at")
