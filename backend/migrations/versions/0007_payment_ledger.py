"""Add durable payment, refund, and callback idempotency records.

Revision ID: 0007_payment_ledger
Revises: 0006_snapshot_ticket_membership
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_payment_ledger"
down_revision = "0006_snapshot_ticket_membership"
branch_labels = None
depends_on = None


def upgrade() -> None:
    payment_status = sa.Enum("PENDING", "SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED",
                             "PARTIALLY_REFUNDED", "REFUNDED", name="payment_status")
    refund_status = sa.Enum("REQUESTED", "PENDING", "SUCCEEDED", "FAILED", name="refund_status")
    webhook_status = sa.Enum("RECEIVED", "PROCESSED", "REJECTED", name="payment_webhook_status")
    op.create_table("payments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("registration_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), server_default="KES", nullable=False),
        sa.Column("status", payment_status, nullable=False),
        sa.Column("provider_checkout_id", sa.String(120), nullable=True),
        sa.Column("provider_merchant_request_id", sa.String(120), nullable=True),
        sa.Column("failure_code", sa.String(80), nullable=True),
        sa.Column("failure_reason", sa.String(500), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("succeeded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_payment_amount_positive"),
        sa.CheckConstraint("attempt > 0", name="ck_payment_attempt_positive"),
        sa.CheckConstraint("length(currency) = 3", name="ck_payment_currency_length"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["registration_id"], ["registrations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "provider_checkout_id", name="uq_payment_provider_checkout"),
        sa.UniqueConstraint("registration_id", "attempt", name="uq_payment_registration_attempt"))
    for name, table, column in [
        ("ix_payments_event_id", "payments", "event_id"),
        ("ix_payments_registration_id", "payments", "registration_id"),
        ("ix_payments_status_created", "payments", None),
    ]:
        op.create_index(name, table, ["status", "created_at"] if column is None else [column])

    op.create_table("refunds",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), server_default="KES", nullable=False),
        sa.Column("status", refund_status, nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("provider_refund_id", sa.String(120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("amount > 0", name="ck_refund_amount_positive"),
        sa.CheckConstraint("length(currency) = 3", name="ck_refund_currency_length"),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "provider_refund_id", name="uq_refund_provider_reference"))
    op.create_index("ix_refunds_payment_id", "refunds", ["payment_id"])
    op.create_index("ix_refunds_payment_status", "refunds", ["payment_id", "status"])

    op.create_table("payment_webhooks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_event_id", sa.String(160), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=True),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column("status", webhook_status, nullable=False),
        sa.Column("rejection_reason", sa.String(160), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "provider_event_id", name="uq_payment_webhook_provider_event"))
    op.create_index("ix_payment_webhooks_payment_id", "payment_webhooks", ["payment_id"])
    op.create_index("ix_payment_webhooks_status_received", "payment_webhooks", ["status", "received_at"])


def downgrade() -> None:
    op.drop_index("ix_payment_webhooks_status_received", table_name="payment_webhooks")
    op.drop_index("ix_payment_webhooks_payment_id", table_name="payment_webhooks")
    op.drop_table("payment_webhooks")
    op.drop_index("ix_refunds_payment_status", table_name="refunds")
    op.drop_index("ix_refunds_payment_id", table_name="refunds")
    op.drop_table("refunds")
    op.drop_index("ix_payments_status_created", table_name="payments")
    op.drop_index("ix_payments_registration_id", table_name="payments")
    op.drop_index("ix_payments_event_id", table_name="payments")
    op.drop_table("payments")
    sa.Enum(name="payment_webhook_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="refund_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="payment_status").drop(op.get_bind(), checkfirst=True)
