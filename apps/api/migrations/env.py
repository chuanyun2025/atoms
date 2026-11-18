from alembic import context
from atoms.core.db import engine

with engine.connect().execution_options(write_lock=True) as connection:
    context.configure(connection=connection, target_metadata=None, transactional_ddl=True)
    with context.begin_transaction():
        context.run_migrations()
