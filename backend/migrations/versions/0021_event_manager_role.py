"""Add a restricted event manager workspace role."""
from alembic import op
import sqlalchemy as sa

revision = "0021_event_manager_role"
down_revision = "0020_workspace_invitations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE workspace_role ADD VALUE IF NOT EXISTS 'EVENT_MANAGER'")


def downgrade() -> None:
    # PostgreSQL does not support removing an enum value without rebuilding
    # every dependent column. Keep the unused value for safe downgrade paths.
    pass
