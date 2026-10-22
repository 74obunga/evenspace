"""Add workspace invitation flow."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from uuid import UUID

revision = "0020_workspace_invitations"
down_revision = "0019_email_verification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    role = postgresql.ENUM(name="workspace_role", create_type=False)
    op.create_table(
        "workspace_invitations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("role", role, nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("invited_by_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invited_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    for col in ("workspace_id", "email", "token_hash", "invited_by_id", "expires_at"):
        op.create_index(f"ix_workspace_invitations_{col}", "workspace_invitations", [col], unique=col == "token_hash")
    op.bulk_insert(
        sa.table(
            "notification_templates", sa.column("id", sa.Uuid()), sa.column("workspace_id", sa.Uuid()),
            sa.column("key", sa.String()), sa.column("channel", sa.String()),
            sa.column("subject_template", sa.String()), sa.column("body_template", sa.Text()),
            sa.column("enabled", sa.Boolean()),
        ),
        [{
            "id": UUID("10000000-0000-0000-0000-00000000000c"), "workspace_id": None,
            "key": "workspace_invitation", "channel": "email",
            "subject_template": "Invitation to join {workspace_name} on EvenSpace",
            "body_template": "You have been invited to join {workspace_name} as a {role}. This link expires in 7 days:\n\n{invitation_url}\n\nIf you did not expect this invitation, you can ignore this email.",
            "enabled": True,
        }],
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM notification_templates WHERE workspace_id IS NULL AND key = 'workspace_invitation'"))
    for col in ("expires_at", "invited_by_id", "token_hash", "email", "workspace_id"):
        op.drop_index(f"ix_workspace_invitations_{col}", table_name="workspace_invitations")
    op.drop_table("workspace_invitations")
