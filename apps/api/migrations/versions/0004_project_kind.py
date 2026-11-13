"""Record the creation mode for each project."""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE projects ADD COLUMN kind TEXT NOT NULL DEFAULT 'web' "
        "CHECK(kind IN ('web','game','slides','video'))"
    )


def downgrade():
    op.drop_column("projects", "kind")
