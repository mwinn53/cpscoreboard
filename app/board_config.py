"""Board settings the admin edits at runtime: watchlist, team aliases, collection filter.

They live in the database and are cached in memory, because every dashboard
render reads them. All writes go through this class, which updates the cache,
so the cache can't go stale within one process (the app runs one process).

On first start, each setting is seeded from its env var (``WATCH_TEAMS``,
``COLLECT_LOCATIONS``, ``COLLECT_DIVISIONS``). After that the database wins,
and changing the env var does nothing; the startup log says so.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Integer, String, Table, delete, insert, select, update

from .collection import CollectionFilter, split_list
from .store import SnapshotStore, metadata

log = logging.getLogger(__name__)

TEAM_RE = re.compile(r"^\d{2}-\d{4}$")  # e.g. 19-1515
ALIAS_MAX = 60

app_settings = Table(
    "app_settings", metadata,
    Column("key", String(64), primary_key=True),
    Column("value", String(2000), nullable=False, default=""),
    Column("updated_at", DateTime, nullable=False),
)

watch_teams = Table(
    "watch_teams", metadata,
    Column("team_number", String(32), primary_key=True),
    Column("position", Integer, nullable=False),
    Column("added_at", DateTime, nullable=False),
)

team_aliases = Table(
    "team_aliases", metadata,
    Column("team_number", String(32), primary_key=True),
    Column("alias", String(ALIAS_MAX), nullable=False),
    Column("updated_at", DateTime, nullable=False),
)

LOCATIONS, DIVISIONS, WATCH_SEEDED = "collect_locations", "collect_divisions", "watch_seeded"
DEFAULT_DIVISION, DEFAULT_STATE, WATCH_LABEL = "default_division", "default_state", "watch_label"
SCHOOL_LOGO_LINK = "school_logo_link"
WATCH_SCHOOL = "watch_school"
LINK_MAX = 500
VIEW_TEXT_MAX = 60


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def normalize_team(value: str) -> str:
    """Return a valid team number, or raise ValueError with a message for the admin."""
    team = value.strip()
    if not TEAM_RE.match(team):
        raise ValueError(f"{team or '(blank)'} isn't a team number like 19-1515.")
    return team


@dataclass(frozen=True)
class ImportResult:
    watch_added: int = 0
    aliases_added: int = 0
    aliases_changed: int = 0
    skipped: tuple[str, ...] = ()


class BoardConfig:
    def __init__(self, store: SnapshotStore):
        self.store = store
        self._mutex = threading.Lock()  # serializes cache updates; the store lock serializes the DB
        with self.store.lock, self.store.engine.connect() as conn:
            settings = dict(conn.execute(select(app_settings.c.key, app_settings.c.value)).all())
            watch = conn.execute(select(watch_teams.c.team_number).order_by(watch_teams.c.position)).scalars()
            aliases = dict(conn.execute(select(team_aliases.c.team_number, team_aliases.c.alias)).all())
        self._settings: dict[str, str] = settings
        self._watch: list[str] = list(watch)
        self._aliases: dict[str, str] = aliases

    # --- seeding ---

    def seed(self, watch: Iterable[str], locations: str, divisions: str, default_division: str = "",
             default_state: str = "", watch_label: str = "Watchlist", watch_school: str = "") -> None:
        """Copy env-var values into the database the first time only."""
        watch = list(watch)
        for key, value in ((DEFAULT_DIVISION, default_division), (DEFAULT_STATE, default_state),
                           (WATCH_LABEL, watch_label), (WATCH_SCHOOL, watch_school)):
            if key not in self._settings:
                self._set(key, value.strip()[:VIEW_TEXT_MAX])
        for key, env_name, value in ((LOCATIONS, "COLLECT_LOCATIONS", locations),
                                     (DIVISIONS, "COLLECT_DIVISIONS", divisions)):
            if key not in self._settings:
                self._set(key, ",".join(split_list(value)))
                log.info("Seeded %s from %s: %r", key, env_name, value)
            elif ",".join(split_list(value)) != self._settings[key] and value:
                log.info("%s is set but ignored; the admin page setting (%r) is used", env_name, self._settings[key])
        if WATCH_SEEDED not in self._settings:
            for team in watch:
                try:
                    self.add_watch(team)
                except ValueError as e:
                    log.warning("WATCH_TEAMS: %s", e)
            self._set(WATCH_SEEDED, "1")
            if watch:
                log.info("Seeded the watchlist from WATCH_TEAMS: %s", ", ".join(watch))
        elif watch and watch != self._watch:
            log.info("WATCH_TEAMS is set but ignored; the admin page watchlist is used")

    # --- reads (memory only) ---

    @property
    def watchlist(self) -> list[str]:
        return list(self._watch)

    @property
    def aliases(self) -> dict[str, str]:
        return dict(self._aliases)

    def alias(self, team_number: str) -> str:
        return self._aliases.get(team_number, "")

    @property
    def locations(self) -> tuple[str, ...]:
        return split_list(self._settings.get(LOCATIONS, ""))

    @property
    def divisions(self) -> tuple[str, ...]:
        return split_list(self._settings.get(DIVISIONS, ""))

    @property
    def default_division(self) -> str:
        return self._settings.get(DEFAULT_DIVISION, "")

    @property
    def default_state(self) -> str:
        return self._settings.get(DEFAULT_STATE, "")

    @property
    def watch_label(self) -> str:
        return self._settings.get(WATCH_LABEL, "") or "Watchlist"

    @property
    def watch_school(self) -> str:
        return self._settings.get(WATCH_SCHOOL, "")

    @property
    def schools(self) -> dict[str, str]:
        """School per team: the district schools, plus the watched teams' school for any
        watched team that isn't listed there (so EMS teams needn't be entered twice)."""
        schools = dict(self._aliases)
        if self.watch_school:
            for team in self._watch:
                schools.setdefault(team, self.watch_school)
        return schools

    @property
    def school_logo_link(self) -> str:
        return self._settings.get(SCHOOL_LOGO_LINK, "")

    def set_school_logo_link(self, url: str) -> None:
        """Blank removes the link. Raises ValueError unless it's an http(s) address."""
        url = url.strip()
        if url:
            from urllib.parse import urlsplit
            parts = urlsplit(url)
            if parts.scheme not in ("http", "https") or not parts.netloc or len(url) > LINK_MAX:
                raise ValueError("Enter a full web address starting with https://, or leave it blank.")
        self._set(SCHOOL_LOGO_LINK, url)

    def set_view(self, default_division: str, default_state: str, watch_label: str,
                 watch_school: str | None = None) -> None:
        self._set(DEFAULT_DIVISION, default_division.strip()[:VIEW_TEXT_MAX])
        self._set(DEFAULT_STATE, default_state.strip()[:VIEW_TEXT_MAX])
        self._set(WATCH_LABEL, " ".join(watch_label.split())[:VIEW_TEXT_MAX])
        if watch_school is not None:
            self._set(WATCH_SCHOOL, " ".join(watch_school.split())[:VIEW_TEXT_MAX])

    def collection_filter(self) -> CollectionFilter:
        return CollectionFilter.from_strings(",".join(self.locations), ",".join(self.divisions), self._watch)

    # --- writes ---

    def get_value(self, key: str) -> str:
        """A raw app setting (for other modules' state, e.g. app/outage.py)."""
        return self._settings.get(key, "")

    def set_value(self, key: str, value: str) -> None:
        if self._settings.get(key) != value:
            self._set(key, value)

    def _set(self, key: str, value: str) -> None:
        with self._mutex, self.store.lock, self.store.engine.begin() as conn:
            if conn.execute(update(app_settings).where(app_settings.c.key == key)
                            .values(value=value, updated_at=_now())).rowcount == 0:
                conn.execute(insert(app_settings).values(key=key, value=value, updated_at=_now()))
            self._settings[key] = value

    def set_filter(self, locations: Iterable[str], divisions: Iterable[str]) -> None:
        self._set(LOCATIONS, ",".join(split_list(",".join(locations))))
        self._set(DIVISIONS, ",".join(split_list(",".join(divisions))))

    def add_watch(self, team: str) -> bool:
        """Add a team; False if it was already watched. Raises ValueError for a bad number."""
        team = normalize_team(team)
        with self._mutex, self.store.lock, self.store.engine.begin() as conn:
            if team in self._watch:
                return False
            conn.execute(insert(watch_teams).values(team_number=team, position=len(self._watch), added_at=_now()))
            self._watch.append(team)
            return True

    def remove_watch(self, team: str) -> bool:
        with self._mutex, self.store.lock, self.store.engine.begin() as conn:
            if team not in self._watch:
                return False
            conn.execute(delete(watch_teams).where(watch_teams.c.team_number == team))
            self._watch.remove(team)
            return True

    def set_alias(self, team: str, alias: str) -> bool:
        """Set (or, with a blank alias, remove) a team's alias. True if anything changed."""
        team = normalize_team(team)
        alias = " ".join(alias.split())[:ALIAS_MAX]
        with self._mutex, self.store.lock, self.store.engine.begin() as conn:
            current = self._aliases.get(team)
            if (current or "") == alias:
                return False
            if not alias:
                conn.execute(delete(team_aliases).where(team_aliases.c.team_number == team))
                del self._aliases[team]
            elif current is None:
                conn.execute(insert(team_aliases).values(team_number=team, alias=alias, updated_at=_now()))
                self._aliases[team] = alias
            else:
                conn.execute(update(team_aliases).where(team_aliases.c.team_number == team)
                             .values(alias=alias, updated_at=_now()))
                self._aliases[team] = alias
            return True

    def import_legacy(self, team_text: str = "", lookups_text: str = "") -> ImportResult:
        """Import the legacy bot's ``runs/team`` (watchlist) and ``runs/lookups`` (aliases).

        Idempotent: teams already watched are left alone, and an alias is only
        written when it differs. Lines with bad team numbers are skipped and reported.
        """
        from .scraper import parse_alias_file, parse_team_file

        added = new_aliases = changed = 0
        skipped: list[str] = []
        for team in parse_team_file(team_text):
            try:
                added += self.add_watch(team)
            except ValueError:
                skipped.append(team)
        for team, alias in parse_alias_file(lookups_text).items():
            try:
                existed = team in self._aliases
                if self.set_alias(team, alias):
                    changed += existed
                    new_aliases += not existed
            except ValueError:
                skipped.append(team)
        return ImportResult(added, new_aliases, changed, tuple(skipped))
