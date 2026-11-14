"""Track the version explicitly published for each project."""
import sqlalchemy as sa
from alembic import op

revision = "0009_publish"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "publications",
        sa.Column("project_id", sa.Text(), sa.ForeignKey("projects.id"), primary_key=True),
        sa.Column("slug", sa.Text(), nullable=False, unique=True),
        sa.Column("version_id", sa.Text(), sa.ForeignKey("versions.id"), nullable=False),
        sa.Column("previous_version_id", sa.Text(), sa.ForeignKey("versions.id")),
        sa.Column("published", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
    )


def downgrade():
    op.drop_table("publications")
