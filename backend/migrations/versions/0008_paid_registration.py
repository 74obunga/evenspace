"""Support payment-pending registrations and paid checkout receipts.

Revision ID: 0008_paid_registration
Revises: 0007_payment_ledger
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_paid_registration"
down_revision = "0007_payment_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Preserve existing enum labels and add the non-ticket-bearing reservation state.
    op.execute("ALTER TYPE registration_status ADD VALUE IF NOT EXISTS 'PENDING_PAYMENT'")
    op.add_column("payments", sa.Column("provider_receipt_id", sa.String(40), nullable=True))
    op.create_unique_constraint(
        "uq_payment_provider_receipt", "payments", ["provider_receipt_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_payment_provider_receipt", "payments", type_="unique")
    op.drop_column("payments", "provider_receipt_id")
    # PostgreSQL does not support removing a single enum label safely.
