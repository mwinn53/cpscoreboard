"""Alembic migrations (app/schema.py): fresh databases, pre-Alembic databases, restarts."""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from alembic.script import ScriptDirectory

from app.schema import MIGRATIONS, metadata

HEAD = ScriptDirectory(str(MIGRATIONS)).get_current_head()
from app.store import SnapshotStore


def _diff(engine):
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True})
        return compare_metadata(ctx, metadata)


def _version(engine):
    with engine.connect() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()


def test_fresh_database_matches_the_code(tmp_path):
    store = SnapshotStore(f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}")
    assert _diff(store.engine) == []
    assert _version(store.engine) == HEAD
    assert set(metadata.tables) <= set(inspect(store.engine).get_table_names())
    store.close()


def test_in_memory_database_migrates():
    store = SnapshotStore("sqlite://")
    assert _diff(store.engine) == [] and _version(store.engine) == HEAD
    store.close()


def test_database_from_before_alembic_is_upgraded_and_stamped(tmp_path):
    from app.schema import BASELINE_TABLES
    url = f"sqlite:///{(tmp_path / 'old.sqlite').as_posix()}"
    old = create_engine(url)
    metadata.create_all(old, tables=[metadata.tables[n] for n in BASELINE_TABLES])  # the app before Alembic
    with old.begin() as conn:
        conn.execute(text("ALTER TABLE devices DROP COLUMN relationship"))  # an older version's schema
        conn.execute(text("DROP TABLE posts"))
        conn.execute(text("INSERT INTO app_settings (key, value, updated_at) VALUES ('k', 'kept', '2026-11-01')"))
    old.dispose()

    store = SnapshotStore(url)
    assert _version(store.engine) == HEAD and _diff(store.engine) == []
    with store.engine.connect() as conn:
        assert conn.execute(text("SELECT value FROM app_settings WHERE key = 'k'")).scalar() == "kept"
    store.close()
    again = SnapshotStore(url)  # a restart changes nothing
    assert _version(again.engine) == HEAD and _diff(again.engine) == []
    again.close()
