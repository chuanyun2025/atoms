"""Initial persistent project, run, artifact and lease model."""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

DDL = [
"""CREATE TABLE visitors(id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE, created_at REAL NOT NULL, expires_at REAL NOT NULL)""",
"""CREATE TABLE projects(id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES visitors(id), client_key TEXT NOT NULL,
title TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0, current_version_id TEXT, active_run_id TEXT,
created_at REAL NOT NULL, updated_at REAL NOT NULL, UNIQUE(owner_id,client_key))""",
"""CREATE TABLE runs(id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), owner_id TEXT NOT NULL REFERENCES visitors(id),
prompt TEXT NOT NULL, base_version_id TEXT, expected_revision INTEGER NOT NULL, status TEXT NOT NULL CHECK(status IN ('pending','running','succeeded','failed','interrupted')),
stage TEXT NOT NULL, created_at REAL NOT NULL, started_at REAL, finished_at REAL, lease_token TEXT, lease_until REAL,
model_calls INTEGER NOT NULL DEFAULT 0, error_code TEXT, error_message TEXT, result_version_id TEXT)""",
"""CREATE UNIQUE INDEX one_active_run ON runs(project_id) WHERE status IN ('pending','running')""",
"""CREATE TABLE messages(id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), run_id TEXT REFERENCES runs(id),
role TEXT NOT NULL CHECK(role IN ('user','assistant','system')), content TEXT NOT NULL, created_at REAL NOT NULL)""",
"""CREATE TABLE run_events(run_id TEXT NOT NULL REFERENCES runs(id), seq INTEGER NOT NULL, type TEXT NOT NULL, payload TEXT NOT NULL, created_at REAL NOT NULL, PRIMARY KEY(run_id,seq))""",
"""CREATE TABLE request_keys(owner_id TEXT NOT NULL REFERENCES visitors(id), key TEXT NOT NULL, request_hash TEXT NOT NULL,
run_id TEXT NOT NULL REFERENCES runs(id), created_at REAL NOT NULL, PRIMARY KEY(owner_id,key))""",
"""CREATE TABLE artifacts(id TEXT PRIMARY KEY, raw_json TEXT NOT NULL, compiled_json TEXT NOT NULL, digest TEXT NOT NULL,
compiler_version TEXT NOT NULL, sdk_version TEXT NOT NULL, validation_json TEXT NOT NULL, created_at REAL NOT NULL)""",
"""CREATE TABLE versions(id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), number INTEGER NOT NULL,
artifact_id TEXT NOT NULL REFERENCES artifacts(id), parent_version_id TEXT REFERENCES versions(id), source_run_id TEXT NOT NULL UNIQUE REFERENCES runs(id),
title TEXT NOT NULL, summary TEXT NOT NULL, created_at REAL NOT NULL, UNIQUE(project_id,number))""",
"""CREATE TABLE project_actions(id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), action TEXT NOT NULL,
from_version_id TEXT, to_version_id TEXT NOT NULL REFERENCES versions(id), created_at REAL NOT NULL)""",
"""CREATE TABLE app_states(project_id TEXT PRIMARY KEY REFERENCES projects(id), revision INTEGER NOT NULL DEFAULT 0, values_json TEXT NOT NULL DEFAULT '{}', updated_at REAL NOT NULL)""",
"""CREATE TABLE quota_windows(key TEXT PRIMARY KEY, count INTEGER NOT NULL, expires_at REAL NOT NULL)""",
"""CREATE TABLE worker_status(id INTEGER PRIMARY KEY CHECK(id=1), lease_token TEXT, lease_until REAL NOT NULL DEFAULT 0, heartbeat_at REAL NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT 'offline', model_configured INTEGER NOT NULL DEFAULT 0)""",
"""INSERT INTO worker_status(id) VALUES(1)""",
"""CREATE TABLE system_settings(key TEXT PRIMARY KEY, value TEXT NOT NULL)""",
]

def upgrade():
    connection = op.get_bind()
    for statement in DDL:
        connection.execute(sa.text(statement))


def downgrade():
    for table in ["system_settings","worker_status","quota_windows","app_states","project_actions","versions","artifacts","request_keys","run_events","messages","runs","projects","visitors"]:
        op.drop_table(table)
