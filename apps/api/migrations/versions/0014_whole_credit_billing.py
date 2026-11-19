"""Record the pricing rule in effect when a call is authorized."""

from alembic import op

revision = "0014_whole_credit_billing"
down_revision = "0013_public_budget_and_passcodes"
branch_labels = None
depends_on = None


def upgrade():
    # Existing authorizations and inserts from older processes use fractional billing.
    for table in ("model_calls", "media_calls"):
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN whole_credit_billing INTEGER NOT NULL DEFAULT 0 "
            "CHECK(whole_credit_billing IN (0,1))"
        )


def downgrade():
    for table in ("model_calls", "media_calls"):
        op.execute(f"ALTER TABLE {table} DROP COLUMN whole_credit_billing")
