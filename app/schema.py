"""Database schema and migrations (Alembic).

Every table is defined on ``app.store.metadata`` by the module that uses it; this
module imports them all so the metadata is complete, and ``migrate()`` brings a
database to the latest revision at startup (``app/migrations/versions/``).

A database created before Alembic (no ``alembic_version`` table, but app tables)
is first brought up to the baseline with the old create-and-add-columns step, then
stamped as the baseline, so production's existing SQLite file carries on as is.

To change the schema: edit the table definition, then from the repo root run
``alembic revision --autogenerate -m "what changed"``, check the generated file
(SQLite ALTERs use batch mode), and commit it.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from . import analysis_store, board_config, branding, devices, posting, store, team_detail  # noqa: F401 (register tables)
from .store import add_missing_columns, metadata

log = logging.getLogger(__name__)

BASELINE = "0001"
# The tables revision 0001 created. A database from before Alembic gets exactly these
# before it's stamped; later tables come from their own revisions.
BASELINE_TABLES = ("app_settings", "board_updates", "devices", "email_codes", "image_snapshots", "posts",
                   "site_images", "team_aliases", "team_snapshots", "watch_teams")
MIGRATIONS = Path(__file__).parent / "migrations"


def _config():
    from alembic.config import Config
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    return cfg


def migrate(engine: Engine) -> None:
    from alembic import command
    cfg = _config()
    tables = set(inspect(engine).get_table_names())
    if "alembic_version" not in tables and tables & set(metadata.tables):
        log.info("Database predates Alembic: bringing it to the baseline and stamping %s", BASELINE)
        metadata.create_all(engine, tables=[metadata.tables[n] for n in BASELINE_TABLES])
        add_missing_columns(engine, BASELINE_TABLES)
        with engine.begin() as conn:
            cfg.attributes["connection"] = conn
            command.stamp(cfg, BASELINE)
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
