"""Add meeting attendee roles and organizer-created guest records."""
from alembic import op
import sqlalchemy as sa

revision = "0023_meeting_attendee_roles"
down_revision = "0022_guest_signature_geo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_meeting_guest_type", "meeting_guest_registrations", type_="check")
    op.create_check_constraint(
        "ck_meeting_guest_type", "meeting_guest_registrations",
        "attendee_type IN ('staff','guest','speaker','secretary','chairperson','member_delegate')",
    )
    op.add_column(
        "meeting_guest_registrations",
        sa.Column("registration_source", sa.String(8), server_default="qr", nullable=False),
    )
    op.add_column(
        "meeting_guest_registrations",
        sa.Column("registered_by_id", sa.Uuid(), nullable=True),
    )
    op.create_check_constraint(
        "ck_meeting_guest_registration_source", "meeting_guest_registrations",
        "registration_source IN ('qr','admin')",
    )
    op.create_foreign_key(
        "fk_meeting_guest_registered_by", "meeting_guest_registrations", "users",
        ["registered_by_id"], ["id"], ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("fk_meeting_guest_registered_by", "meeting_guest_registrations", type_="foreignkey")
    op.drop_constraint("ck_meeting_guest_registration_source", "meeting_guest_registrations", type_="check")
    op.drop_column("meeting_guest_registrations", "registered_by_id")
    op.drop_column("meeting_guest_registrations", "registration_source")
    op.execute(
        "UPDATE meeting_guest_registrations SET attendee_type = 'guest' "
        "WHERE attendee_type IN ('speaker','secretary','chairperson','member_delegate')"
    )
    op.drop_constraint("ck_meeting_guest_type", "meeting_guest_registrations", type_="check")
    op.create_check_constraint(
        "ck_meeting_guest_type", "meeting_guest_registrations",
        "attendee_type IN ('staff','guest')",
    )
