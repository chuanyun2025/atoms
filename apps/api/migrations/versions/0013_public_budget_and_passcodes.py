"""Add passcodes, visitor bindings, and call passcode tracking for public guardrails."""

from alembic import op

revision = "0013_public_budget_and_passcodes"
down_revision = "0012_query_indexes"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """CREATE TABLE passcodes (
            id TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            code_hash TEXT NOT NULL UNIQUE,
            budget_units INTEGER NOT NULL,
            spent_units INTEGER NOT NULL DEFAULT 0,
            held_units INTEGER NOT NULL DEFAULT 0,
            max_visitors INTEGER NOT NULL DEFAULT 1,
            bypass_daily_budget INTEGER NOT NULL DEFAULT 1,
            allow_video INTEGER NOT NULL DEFAULT 1,
            expires_at REAL,
            revoked_at REAL,
            created_at REAL NOT NULL
        )"""
    )
    op.execute(
        """CREATE TABLE visitor_passcodes (
            visitor_id TEXT NOT NULL REFERENCES visitors(id),
            passcode_id TEXT NOT NULL REFERENCES passcodes(id),
            active INTEGER NOT NULL DEFAULT 1,
            bound_at REAL NOT NULL,
            PRIMARY KEY (visitor_id, passcode_id)
        )"""
    )
    op.execute("CREATE INDEX visitor_passcodes_active ON visitor_passcodes(visitor_id, active)")
    op.execute("ALTER TABLE model_calls ADD COLUMN passcode_id TEXT")
    op.execute("ALTER TABLE media_calls ADD COLUMN passcode_id TEXT")
    op.execute("CREATE INDEX model_calls_public_created ON model_calls(passcode_id, status, created_at)")
    op.execute("CREATE INDEX media_calls_public_created ON media_calls(passcode_id, status, created_at)")
    op.execute("CREATE INDEX credit_ledger_kind_created ON credit_ledger(kind, created_at)")


def downgrade():
    op.execute("DROP INDEX IF EXISTS credit_ledger_kind_created")
    op.execute("DROP INDEX IF EXISTS media_calls_public_created")
    op.execute("DROP INDEX IF EXISTS model_calls_public_created")
    op.execute("DROP INDEX IF EXISTS visitor_passcodes_active")
    op.execute("DROP TABLE IF EXISTS visitor_passcodes")
    op.execute("DROP TABLE IF EXISTS passcodes")
