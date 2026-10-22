"""Add physical/online meeting mode and online meeting link."""
from alembic import op
import sqlalchemy as sa

revision = "0017_online_meeting_link"
down_revision = "0016_meeting_guest_join"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "meetings",
        sa.Column("meeting_mode", sa.String(16), server_default="physical", nullable=False),
    )
    op.add_column("meetings", sa.Column("online_url", sa.String(500), nullable=True))
    op.create_check_constraint("ck_meeting_mode", "meetings", "meeting_mode IN ('physical','online')")
    op.create_check_constraint(
        "ck_online_meeting_url", "meetings",
        "(meeting_mode = 'physical' AND online_url IS NULL) OR "
        "(meeting_mode = 'online' AND online_url IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_online_meeting_url", "meetings", type_="check")
    op.drop_constraint("ck_meeting_mode", "meetings", type_="check")
    op.drop_column("meetings", "online_url")
    op.drop_column("meetings", "meeting_mode")
