"""Anonymous wallets, exact token ledger and call reservations."""
from alembic import op
import sqlalchemy as sa

revision="0002"
down_revision="0001"
branch_labels=None
depends_on=None

DDL=[
"""CREATE TABLE credit_wallets(visitor_id TEXT PRIMARY KEY REFERENCES visitors(id),
balance_units INTEGER NOT NULL CHECK(balance_units>=0),held_units INTEGER NOT NULL DEFAULT 0 CHECK(held_units>=0 AND held_units<=balance_units),
spent_units INTEGER NOT NULL DEFAULT 0 CHECK(spent_units>=0),created_at REAL NOT NULL,updated_at REAL NOT NULL)""",
"""CREATE TABLE model_calls(id TEXT PRIMARY KEY,visitor_id TEXT NOT NULL REFERENCES visitors(id),
run_id TEXT NOT NULL REFERENCES runs(id),attempt INTEGER NOT NULL,lease_token TEXT NOT NULL,
status TEXT NOT NULL CHECK(status IN ('in_flight','settled','released','uncertain')),
reserved_units INTEGER NOT NULL CHECK(reserved_units>=0),input_ceiling INTEGER NOT NULL,output_limit INTEGER NOT NULL,
input_tokens INTEGER,output_tokens INTEGER,provider_request_id TEXT,error_code TEXT,created_at REAL NOT NULL,settled_at REAL,
UNIQUE(run_id,attempt))""",
"""CREATE TABLE credit_ledger(id TEXT PRIMARY KEY,visitor_id TEXT NOT NULL REFERENCES visitors(id),event_key TEXT NOT NULL,
kind TEXT NOT NULL,amount_units INTEGER NOT NULL,input_tokens INTEGER NOT NULL DEFAULT 0,output_tokens INTEGER NOT NULL DEFAULT 0,
run_id TEXT REFERENCES runs(id),call_id TEXT REFERENCES model_calls(id),created_at REAL NOT NULL,UNIQUE(visitor_id,event_key))""",
"""INSERT INTO credit_wallets(visitor_id,balance_units,created_at,updated_at)
SELECT id,500000000,CAST(strftime('%s','now') AS REAL),CAST(strftime('%s','now') AS REAL) FROM visitors""",
"""INSERT INTO credit_ledger(id,visitor_id,event_key,kind,amount_units,created_at)
SELECT lower(hex(randomblob(16))),id,'welcome','welcome',500000000,CAST(strftime('%s','now') AS REAL) FROM visitors""",
"""CREATE INDEX credit_ledger_owner_time ON credit_ledger(visitor_id,created_at)""",
]

def upgrade():
    for sql in DDL:
        op.get_bind().execute(sa.text(sql))

def downgrade():
    for table in ["credit_ledger","model_calls","credit_wallets"]:
        op.drop_table(table)
