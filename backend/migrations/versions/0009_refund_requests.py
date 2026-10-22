"""Add idempotency to refund requests.

Revision ID: 0009_refund_requests
Revises: 0008_paid_registration
"""
from alembic import op
import sqlalchemy as sa

revision = "0009_refund_requests"
down_revision = "0008_paid_registration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("refunds", sa.Column("idempotency_key_hash", sa.String(64), nullable=True))
    op.add_column("refunds", sa.Column("request_digest", sa.String(64), nullable=True))
    # Existing rows predate refund requests. Backfill unique stable values before enforcing.
    op.execute("UPDATE refunds SET idempotency_key_hash = md5(id::text), request_digest = md5(id::text)")
    op.alter_column("refunds", "idempotency_key_hash", nullable=False)
    op.alter_column("refunds", "request_digest", nullable=False)
    op.create_unique_constraint(
        "uq_refund_payment_idempotency", "refunds", ["payment_id", "idempotency_key_hash"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_refund_payment_idempotency", "refunds", type_="unique")
    op.drop_column("refunds", "request_digest")
    op.drop_column("refunds", "idempotency_key_hash")
