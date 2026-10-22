"""Store private meeting attachments."""
from alembic import op
import sqlalchemy as sa

revision = "0012_meeting_attachments"
down_revision = "0011_meeting_invitees"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "meeting_attachments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("media_type", sa.String(120), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("uploaded_by_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("size_bytes > 0", name="ck_meeting_attachment_size_positive"),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["uploaded_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_meeting_attachments_meeting_id", "meeting_attachments", ["meeting_id"])


def downgrade() -> None:
    op.drop_index("ix_meeting_attachments_meeting_id", table_name="meeting_attachments")
    op.drop_table("meeting_attachments")
