"""Meter native video in the shared wallet and allow text-only inputs."""
from alembic import op
import sqlalchemy as sa

revision="0007"
down_revision="0006"
branch_labels=None
depends_on=None


def upgrade():
    op.execute("""CREATE TABLE media_calls(
        id TEXT PRIMARY KEY,visitor_id TEXT NOT NULL REFERENCES visitors(id),run_id TEXT NOT NULL REFERENCES runs(id),
        active_run_id TEXT NOT NULL REFERENCES runs(id),purpose TEXT NOT NULL CHECK(purpose IN ('image','video')),
        status TEXT NOT NULL CHECK(status IN ('reserved','in_flight','settled','released','uncertain')),
        reserved_units INTEGER NOT NULL CHECK(reserved_units>=0),estimated_provider_credits INTEGER NOT NULL,
        credit_price_cny TEXT NOT NULL,actual_provider_credits INTEGER,provider_task_id TEXT,error_code TEXT,
        created_at REAL NOT NULL,settled_at REAL,UNIQUE(run_id,purpose))""")
    op.execute("CREATE INDEX media_calls_owner_status ON media_calls(visitor_id,status)")
    op.execute("CREATE INDEX media_calls_active_run ON media_calls(active_run_id)")
    op.execute("ALTER TABLE credit_ledger ADD COLUMN media_call_id TEXT REFERENCES media_calls(id)")
    with op.batch_alter_table("video_jobs") as batch:
        batch.alter_column("image_asset_id",existing_type=sa.Text(),nullable=True)
        batch.add_column(sa.Column("input_mode",sa.Text(),nullable=False,server_default="image"))
        batch.add_column(sa.Column("video_call_id",sa.Text()))
        batch.create_foreign_key("fk_video_video_call","media_calls",["video_call_id"],["id"])


def downgrade():
    raise RuntimeError("含积分账本的迁移请通过对应版本备份恢复，不允许丢弃消费记录")
