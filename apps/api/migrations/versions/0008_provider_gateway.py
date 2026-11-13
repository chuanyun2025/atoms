"""Publish provider capability flags in the worker heartbeat."""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("worker_status", sa.Column("video_configured", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("worker_status", sa.Column("text_model", sa.Text()))


def downgrade():
    op.drop_column("worker_status", "text_model")
    op.drop_column("worker_status", "video_configured")
