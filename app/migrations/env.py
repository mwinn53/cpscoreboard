"""Alembic environment: runs on the app's engine (startup) or the configured database (CLI)."""

from alembic import context
from sqlalchemy import create_engine

from app.schema import metadata

config = context.config


def _run(connection) -> None:
    context.configure(connection=connection, target_metadata=metadata, render_as_batch=True,
                      compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


connection = config.attributes.get("connection")
if connection is not None:  # app startup: app/schema.py passes its connection
    _run(connection)
else:  # command line: the database from the app's settings
    from app.config import Settings
    engine = create_engine(Settings().effective_database_url)
    with engine.begin() as conn:
        _run(conn)
