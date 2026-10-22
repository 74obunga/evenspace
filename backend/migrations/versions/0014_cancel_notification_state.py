"""Allow queued notification cancellation."""
from alembic import op
import sqlalchemy as sa

revision = "0014_cancel_notification_state"
down_revision = "0013_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_notification_status", "notifications", type_="check")
    op.create_check_constraint("ck_notification_status", "notifications",
                                "status IN ('pending','sent','failed','cancelled')")


def downgrade() -> None:
    op.execute(sa.text("UPDATE notifications SET status='failed' WHERE status='cancelled'"))
    op.drop_constraint("ck_notification_status", "notifications", type_="check")
    op.create_check_constraint("ck_notification_status", "notifications",
                                "status IN ('pending','sent','failed')")
