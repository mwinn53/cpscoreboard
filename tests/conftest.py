import gzip
from pathlib import Path

import pytest
from sqlalchemy import inspect, text

FIXTURES = Path(__file__).parent / "fixtures"
S17 = FIXTURES / "scores_s17_2024-11-21.json.gz"  # season 17: has adjustment/score_3/total
S19 = FIXTURES / "scores_s19_2026-11-13.json.gz"  # season 19: has tier, no totals


def load(path: Path) -> bytes:
    with gzip.open(path, "rb") as f:
        return f.read()


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def _fast_new_databases(monkeypatch):
    """Create an empty test database straight from the table definitions, stamped at head.

    Replaying every Alembic revision costs ~0.4 s per database, and nearly every test makes one.
    Databases that already have tables (pre-Alembic, or older revisions) still migrate for real, and
    tests/test_schema.py overrides this fixture so it checks the real path from scratch."""
    from app import schema
    real = schema.migrate

    def fast(engine):
        if inspect(engine).get_table_names():
            return real(engine)
        schema.metadata.create_all(engine)
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"))
            conn.execute(text("INSERT INTO alembic_version VALUES (:v)"), {"v": _head()})

    monkeypatch.setattr(schema, "migrate", fast)


@pytest.fixture(autouse=True)
def _no_disk_flushes(monkeypatch):
    """Test databases are thrown away, so commits needn't wait for the disk (slow on Windows)."""
    from app import store
    monkeypatch.setattr(store, "SQLITE_PRAGMAS", ("journal_mode=WAL", "synchronous=OFF"))


_PARSED: dict[bytes, list] = {}


@pytest.fixture(autouse=True)
def _parse_each_capture_once(monkeypatch):
    """Every test app replays the same fixture scoreboards; parse each one once per run.

    TeamScore is frozen, so sharing the parsed teams between tests is safe (each call gets its own list)."""
    from app import poller
    real = poller.parse_scores

    def cached(payload):
        if not isinstance(payload, bytes):
            return real(payload)
        if payload not in _PARSED:
            _PARSED[payload] = real(payload)
        return list(_PARSED[payload])

    monkeypatch.setattr(poller, "parse_scores", cached)


@pytest.fixture(autouse=True)
def _short_waits(monkeypatch):
    """Deliberate production waits (guessing penalty, retry back-off, the collector's pause between
    teams) aren't what the tests check."""
    from app import analysis_collector, auth
    monkeypatch.setattr(auth, "CLAIM_DELAY", 0)
    monkeypatch.setattr(analysis_collector, "FETCH_RETRY_DELAY", 0)
    monkeypatch.setattr(analysis_collector, "PAUSE", 0)


_HEAD: list[str] = []


def _head() -> str:
    if not _HEAD:
        from alembic.script import ScriptDirectory

        from app.schema import MIGRATIONS
        _HEAD.append(ScriptDirectory(str(MIGRATIONS)).get_current_head())
    return _HEAD[0]
