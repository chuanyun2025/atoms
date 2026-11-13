"""Retain failed candidates and explicitly link user-requested repair runs."""
from alembic import op
import sqlalchemy as sa

revision="0003"
down_revision="0002"
branch_labels=None
depends_on=None


def upgrade():
    conn=op.get_bind()
    conn.execute(sa.text("ALTER TABLE runs ADD COLUMN retry_of_run_id TEXT REFERENCES runs(id)"))
    conn.execute(sa.text("""CREATE TABLE run_candidates(
        run_id TEXT PRIMARY KEY REFERENCES runs(id),raw_content TEXT NOT NULL,
        diagnostics TEXT NOT NULL DEFAULT '',attempt INTEGER NOT NULL,
        created_at REAL NOT NULL,updated_at REAL NOT NULL)"""))


def downgrade():
    op.drop_table("run_candidates")
    op.drop_column("runs","retry_of_run_id")
