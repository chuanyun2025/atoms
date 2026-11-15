"""Distinguish model reservations from calls authorized for dispatch."""
from alembic import op

revision = "0011_model_call_dispatch"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE model_calls ADD COLUMN dispatch_pending INTEGER NOT NULL DEFAULT 0 CHECK(dispatch_pending IN (0,1))")


def downgrade():
    op.execute("ALTER TABLE model_calls DROP COLUMN dispatch_pending")
