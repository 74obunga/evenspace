"""Add meeting invitees, attendance, and cancellation reason."""
from alembic import op
import sqlalchemy as sa

revision = "0011_meeting_invitees"
down_revision = "0010_meeting_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("meetings", sa.Column("cancellation_reason", sa.String(500), nullable=True))
    op.create_table(
        "meeting_invitees",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("invited_by_id", sa.Uuid(), nullable=False),
        sa.Column("invited_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("attendance_status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("attendance_note", sa.String(500), nullable=True),
        sa.Column("recorded_by_id", sa.Uuid(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("attendance_status IN ('pending','present','absent','excused')", name="ck_meeting_attendance_status"),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["invited_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["recorded_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("meeting_id", "user_id", name="uq_meeting_invitee"),
    )
    op.create_index("ix_meeting_invitees_meeting_id", "meeting_invitees", ["meeting_id"])
    op.create_index("ix_meeting_invitees_user_id", "meeting_invitees", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_meeting_invitees_user_id", table_name="meeting_invitees")
    op.drop_index("ix_meeting_invitees_meeting_id", table_name="meeting_invitees")
    op.drop_table("meeting_invitees")
    op.drop_column("meetings", "cancellation_reason")
