"""Alembic migrations (app/schema.py): fresh databases, pre-Alembic databases, restarts."""

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from alembic.script import ScriptDirectory

from app.schema import MIGRATIONS, metadata

HEAD = ScriptDirectory(str(MIGRATIONS)).get_current_head()
from app.store import SnapshotStore


@pytest.fixture(autouse=True)
def _fast_new_databases():
    """Overrides conftest's shortcut: these tests are the ones that check the real migrations."""


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


def test_0005_drops_rows_caused_only_by_cross_division_places(tmp_path):
    from alembic import command

    from app.schema import _config
    url = f"sqlite:///{(tmp_path / 'snap.sqlite').as_posix()}"
    engine = create_engine(url)
    cfg = _config()
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "0004")
    cols = ("team_number, observed_at, location, division, tier, images, play_time, score_time, ccs_score, "
            "adjustment, total, code, place_overall, place_division, place_state, place_state_division")

    def row(i, score, overall, nat):
        return (f"('19-0001', '2026-11-14 12:{i:02d}:00', 'GA', 'Middle School', 'Middle School', 2, {i * 60}, 0, "
                f"{score}, NULL, NULL, '', {overall}, {nat}, {overall}, 3)")
    rows = [row(0, 10, 900, 50), row(1, 10, 901, 50), row(2, 10, 902, 50),   # only the overall place moved
            row(3, 20, 880, 45), row(4, 20, 881, 44), row(5, 20, 882, 44)]  # a score; a national place; overall only
    with engine.begin() as conn:
        conn.execute(text(f"INSERT INTO team_snapshots ({cols}) VALUES {', '.join(rows)}"))
    engine.dispose()

    store = SnapshotStore(url)  # upgrades to head (and vacuums)
    with store.engine.connect() as conn:
        kept = conn.execute(text("SELECT ccs_score, place_division FROM team_snapshots ORDER BY observed_at")).all()
    assert [tuple(r) for r in kept] == [(10, 50), (20, 45), (20, 44)] and _version(store.engine) == HEAD
    store.close()
