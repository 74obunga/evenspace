"""Store meeting guest signatures and optional location metadata."""
from alembic import op
import sqlalchemy as sa

revision = "0022_guest_signature_geo"
down_revision = "0021_event_manager_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("meeting_guest_registrations", sa.Column("signature_png", sa.LargeBinary(), nullable=True))
    op.add_column("meeting_guest_registrations", sa.Column("gps_latitude", sa.Float(), nullable=True))
    op.add_column("meeting_guest_registrations", sa.Column("gps_longitude", sa.Float(), nullable=True))
    op.add_column("meeting_guest_registrations", sa.Column("gps_accuracy_m", sa.Float(), nullable=True))
    op.add_column("meeting_guest_registrations", sa.Column("gps_captured_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "ck_meeting_guest_gps_pair", "meeting_guest_registrations",
        "(gps_latitude IS NULL AND gps_longitude IS NULL) OR "
        "(gps_latitude IS NOT NULL AND gps_longitude IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_meeting_guest_gps_latitude", "meeting_guest_registrations",
        "gps_latitude IS NULL OR gps_latitude BETWEEN -90 AND 90",
    )
    op.create_check_constraint(
        "ck_meeting_guest_gps_longitude", "meeting_guest_registrations",
        "gps_longitude IS NULL OR gps_longitude BETWEEN -180 AND 180",
    )
    op.create_check_constraint(
        "ck_meeting_guest_gps_accuracy", "meeting_guest_registrations",
        "gps_accuracy_m IS NULL OR gps_accuracy_m BETWEEN 0 AND 100000",
    )
    op.create_check_constraint(
        "ck_meeting_guest_signature_size", "meeting_guest_registrations",
        "signature_png IS NULL OR length(signature_png) BETWEEN 1 AND 98304",
    )


def downgrade() -> None:
    op.drop_constraint("ck_meeting_guest_signature_size", "meeting_guest_registrations", type_="check")
    op.drop_constraint("ck_meeting_guest_gps_accuracy", "meeting_guest_registrations", type_="check")
    op.drop_constraint("ck_meeting_guest_gps_longitude", "meeting_guest_registrations", type_="check")
    op.drop_constraint("ck_meeting_guest_gps_latitude", "meeting_guest_registrations", type_="check")
    op.drop_constraint("ck_meeting_guest_gps_pair", "meeting_guest_registrations", type_="check")
    op.drop_column("meeting_guest_registrations", "gps_captured_at")
    op.drop_column("meeting_guest_registrations", "gps_accuracy_m")
    op.drop_column("meeting_guest_registrations", "gps_longitude")
    op.drop_column("meeting_guest_registrations", "gps_latitude")
    op.drop_column("meeting_guest_registrations", "signature_png")
