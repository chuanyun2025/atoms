"""Add indexes for hot project, message, run, credit, and media queries."""
from alembic import op

revision = "0012_query_indexes"
down_revision = "0011_model_call_dispatch"
branch_labels = None
depends_on = None

INDEXES = [
    ("projects_owner_updated", "CREATE INDEX IF NOT EXISTS projects_owner_updated ON projects(owner_id, updated_at DESC)"),
    ("messages_project_created", "CREATE INDEX IF NOT EXISTS messages_project_created ON messages(project_id, created_at, id)"),
    ("runs_status_created", "CREATE INDEX IF NOT EXISTS runs_status_created ON runs(status, created_at, id)"),
    ("model_calls_owner_status", "CREATE INDEX IF NOT EXISTS model_calls_owner_status ON model_calls(visitor_id, status, created_at)"),
    ("media_assets_project_mime_created", "CREATE INDEX IF NOT EXISTS media_assets_project_mime_created ON media_assets(project_id, mime_type, created_at)"),
]


def upgrade():
    for _, sql in INDEXES:
        op.execute(sql)


def downgrade():
    for name, _ in reversed(INDEXES):
        op.execute(f"DROP INDEX IF EXISTS {name}")
