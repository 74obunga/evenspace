"""Add public guest registration for scheduled meetings."""
from alembic import op
import sqlalchemy as sa

revision = "0016_meeting_guest_join"
down_revision = "0015_ticket_email_secrets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("meetings", sa.Column("join_token_hash", sa.String(64), nullable=True))
    op.create_unique_constraint("uq_meetings_join_token_hash", "meetings", ["join_token_hash"])
    op.create_table(
        "meeting_guest_registrations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("phone", sa.String(24), nullable=False),
        sa.Column("attendee_type", sa.String(16), nullable=False),
        sa.Column("organization", sa.String(200), nullable=True),
        sa.Column("attendance_status", sa.String(16), server_default="registered", nullable=False),
        sa.Column("attendance_note", sa.String(500), nullable=True),
        sa.Column("recorded_by_id", sa.Uuid(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("registered_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("attendee_type IN ('staff','guest')", name="ck_meeting_guest_type"),
        sa.CheckConstraint("attendance_status IN ('registered','present','absent','excused')", name="ck_meeting_guest_attendance"),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["recorded_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("meeting_id", "email", name="uq_meeting_guest_email"),
    )
    op.create_index("ix_meeting_guest_registrations_meeting_id", "meeting_guest_registrations", ["meeting_id"])
    op.create_index("ix_meeting_guest_registration", "meeting_guest_registrations", ["meeting_id", "registered_at"])


def downgrade() -> None:
    op.drop_index("ix_meeting_guest_registration", table_name="meeting_guest_registrations")
    op.drop_index("ix_meeting_guest_registrations_meeting_id", table_name="meeting_guest_registrations")
    op.drop_table("meeting_guest_registrations")
    op.drop_constraint("uq_meetings_join_token_hash", "meetings", type_="unique")
    op.drop_column("meetings", "join_token_hash")
