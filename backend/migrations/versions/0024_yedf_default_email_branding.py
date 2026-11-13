"""Update default notification templates to YEDF SPACE identity."""
from alembic import op


revision = "0024_yedf_email_branding"
down_revision = "0023_meeting_attendee_roles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE notification_templates
        SET subject_template = replace(subject_template, 'EvenSpace', 'YEDF SPACE'),
            body_template = replace(body_template, 'EvenSpace', 'YEDF SPACE')
        WHERE workspace_id IS NULL
          AND (subject_template LIKE '%EvenSpace%' OR body_template LIKE '%EvenSpace%')
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE notification_templates
        SET subject_template = replace(subject_template, 'YEDF SPACE', 'EvenSpace'),
            body_template = replace(body_template, 'YEDF SPACE', 'EvenSpace')
        WHERE workspace_id IS NULL
          AND (subject_template LIKE '%YEDF SPACE%' OR body_template LIKE '%YEDF SPACE%')
    """)
