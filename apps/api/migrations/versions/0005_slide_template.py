"""Keep the selected slide template with the project draft."""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE projects ADD COLUMN slide_template_id TEXT "
        "CHECK(slide_template_id IS NULL OR kind = 'slides')"
    )


def downgrade():
    op.drop_column("projects", "slide_template_id")
