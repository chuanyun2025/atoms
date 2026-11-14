"""Store source and sandboxed preview snapshots while a run is building."""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "run_workspace",
        sa.Column("run_id", sa.Text(), sa.ForeignKey("runs.id"), primary_key=True),
        sa.Column("source_json", sa.Text(), nullable=False),
        sa.Column("source_revision", sa.Integer(), nullable=False),
        sa.Column("compiled_json", sa.Text()),
        sa.Column("digest", sa.Text()),
    )


def downgrade():
    op.drop_table("run_workspace")
