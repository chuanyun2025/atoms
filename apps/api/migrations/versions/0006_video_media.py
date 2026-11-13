"""Durable image inputs, video outputs and upstream task checkpoints."""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    conn.execute(sa.text("""CREATE TABLE media_assets(
        id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
        mime_type TEXT NOT NULL, size_bytes INTEGER NOT NULL, sha256 TEXT NOT NULL,
        created_at REAL NOT NULL)"""))
    conn.execute(sa.text("""CREATE TABLE video_jobs(
        run_id TEXT PRIMARY KEY REFERENCES runs(id), image_asset_id TEXT NOT NULL REFERENCES media_assets(id),
        model TEXT NOT NULL, resolution TEXT NOT NULL, duration INTEGER NOT NULL, audio INTEGER NOT NULL,
        phase TEXT NOT NULL DEFAULT 'pending', provider_task_id TEXT, output_asset_id TEXT REFERENCES media_assets(id),
        provider_credits INTEGER, updated_at REAL NOT NULL)"""))


def downgrade():
    op.drop_table("video_jobs")
    op.drop_table("media_assets")
