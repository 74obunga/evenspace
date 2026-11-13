"""Add optional physical location to scheduled meetings."""
from alembic import op
import sqlalchemy as sa


revision = "0025_meeting_location"
down_revision = "0024_yedf_email_branding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("meetings", sa.Column("location", sa.String(300), nullable=True))


def downgrade() -> None:
    op.drop_column("meetings", "location")
