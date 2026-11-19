"""Distinguish fixed video prices from earlier usage-based reservations."""

from alembic import op

revision = "0015_fixed_video_price"
down_revision = "0014_whole_credit_billing"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE media_calls ADD COLUMN fixed_price INTEGER NOT NULL DEFAULT 0 CHECK(fixed_price IN (0,1))")


def downgrade():
    op.execute("ALTER TABLE media_calls DROP COLUMN fixed_price")
