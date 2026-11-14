"""Posting updates about the watched teams (M5): to X, to the log (dry run), or nowhere.

Pieces:

* ``Notifier``: where a post goes. ``LogNotifier`` (dry run) and ``XNotifier``
  (X API v2, OAuth 1.0a user context). Pluggable, since X may be dropped later.
* ``PostSettings``: what the admin set on /admin/config, kept in ``app_settings``.
  The four X credentials are encrypted with ``SECRETS_KEY`` (app/secret_box.py).
* ``PostPlanner``: turns successive boards into messages, as the legacy bot did:
  a watched team appears on the board; **live changes** to its score or places
  while it's actively playing (from a set number of hours in, 4 by default); an
  hour left; time up; then, once it's **done** (time up, or play time stopped for
  20 minutes), **periodic place updates**: at most every N minutes, and only when
  a place moved. The first board after a start only primes the state, so a restart
  doesn't repeat posts.
* ``Poster``: applies the hourly and daily limits, sends, and keeps a log in the
  ``posts`` table for the admin page.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Protocol
from urllib.parse import quote

import httpx
from sqlalchemy import Column, DateTime, Integer, String, Table, Text, func, insert, select

from .board_config import BoardConfig
from .scraper import TeamScore
from .secret_box import SecretBox
from .store import SnapshotStore, _from_db, _to_db, metadata

log = logging.getLogger(__name__)

X_POST_URL = "https://api.x.com/2/tweets"
X_MAX_CHARS = 280
ROUND_SECONDS = 6 * 3600

posts = Table(
    "posts", metadata,
    Column("id", Integer, primary_key=True),
    Column("at", DateTime, nullable=False, index=True),  # UTC, stored naive
    Column("kind", String(32), nullable=False),
    Column("team_number", String(32), nullable=False, default=""),
    Column("text", Text, nullable=False),
    Column("target", String(16), nullable=False),        # x, log
    Column("status", String(16), nullable=False),        # sent, failed, skipped
    Column("detail", Text, nullable=False, default=""),  # remote id, error, or why skipped
)

# --- Settings ---

MODES = ("dry_run", "x")
KINDS = {
    "on_board": "A watched team appears on the board",
    "change": "Live changes while the team is playing (score and places)",
    "hour_left": "A team has about an hour left",
    "time_up": "A team's time is up",
    "place": "Periodic place changes once the team is done",
}
DONE_AFTER = timedelta(minutes=20)  # play time not moving this long = the team is done
CREDENTIALS = ("x_api_key", "x_api_secret", "x_access_token", "x_access_secret")
CREDENTIAL_LABELS = {"x_api_key": "API key (consumer key)", "x_api_secret": "API key secret",
                     "x_access_token": "Access token", "x_access_secret": "Access token secret"}


@dataclass
class PostSettings:
    enabled: bool = True
    mode: str = "dry_run"
    kinds: set[str] = field(default_factory=lambda: set(KINDS))
    change_after_hours: float = 4.0  # live changes only once a team has played this long
    place_every_minutes: int = 30    # after a team is done: at most one place update this often
    per_hour: int = 10
    per_day: int = 40
    footer: str = ""

    @classmethod
    def load(cls, board: BoardConfig) -> PostSettings:
        s = cls()
        s.mode = m if (m := board.get_value("post_mode")) in MODES else s.mode
        s.enabled = board.get_value("post_enabled") != "0"
        if (kinds := board.get_value("post_kinds")) or board.get_value("post_kinds_set"):
            s.kinds = {k for k in kinds.split(",") if k in KINDS}
        for name, conv in (("change_after_hours", float), ("place_every_minutes", int), ("per_hour", int),
                           ("per_day", int)):
            raw = board.get_value(f"post_{name}")
            if raw:
                try:
                    setattr(s, name, conv(raw))
                except ValueError:
                    pass
        s.footer = board.get_value("post_footer")
        return s

    def save(self, board: BoardConfig) -> None:
        board.set_value("post_enabled", "1" if self.enabled else "0")
        board.set_value("post_mode", self.mode)
        board.set_value("post_place_every_minutes", str(self.place_every_minutes))
        board.set_value("post_kinds", ",".join(sorted(self.kinds)))
        board.set_value("post_kinds_set", "1")
        board.set_value("post_change_after_hours", f"{self.change_after_hours:g}")
        board.set_value("post_per_hour", str(self.per_hour))
        board.set_value("post_per_day", str(self.per_day))
        board.set_value("post_footer", self.footer)


class Credentials:
    """The X keys, encrypted at rest in app_settings."""

    def __init__(self, board: BoardConfig, box: SecretBox):
        self.board, self.box = board, box

    def saved(self) -> set[str]:
        return {k for k in CREDENTIALS if self.board.get_value(k)}

    def set(self, name: str, value: str) -> None:
        if name not in CREDENTIALS:
            raise KeyError(name)
        self.board.set_value(name, self.box.encrypt(value) if value else "")

    def get(self) -> dict[str, str] | None:
        """All four, decrypted, or None if any is missing or unreadable."""
        out = {}
        for k in CREDENTIALS:
            raw = self.board.get_value(k)
            value = self.box.decrypt(raw) if raw else None
            if not value:
                return None
            out[k] = value
        return out


# --- Notifiers ---

class Notifier(Protocol):
    target: str

    async def post(self, text: str) -> str:
        """Send one post; returns a remote id (or a note). Raises on failure."""


class LogNotifier:
    target = "log"

    async def post(self, text: str) -> str:
        log.info("[dry run] would post: %s", text)
        return "dry run"


def _pct(s: str) -> str:
    return quote(s, safe="~-._")


def oauth1_header(method: str, url: str, creds: dict[str, str], *, nonce: str | None = None,
                  timestamp: int | None = None, extra: dict[str, str] | None = None) -> str:
    """OAuth 1.0a HMAC-SHA1 Authorization header.

    ``extra``: query or form parameters, which are signed too. X API v2 takes a JSON
    body, which isn't signed, so posting passes none.
    """
    params = {
        "oauth_consumer_key": creds["x_api_key"],
        "oauth_nonce": nonce or secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(timestamp if timestamp is not None else int(time.time())),
        "oauth_token": creds["x_access_token"],
        "oauth_version": "1.0",
    }
    signed = {**(extra or {}), **params}
    param_str = "&".join(f"{_pct(k)}={_pct(v)}" for k, v in sorted(signed.items()))
    base = "&".join([method.upper(), _pct(url), _pct(param_str)])
    key = f"{_pct(creds['x_api_secret'])}&{_pct(creds['x_access_secret'])}"
    params["oauth_signature"] = base64.b64encode(
        hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()).decode()
    return "OAuth " + ", ".join(f'{_pct(k)}="{_pct(v)}"' for k, v in sorted(params.items()))


class XNotifier:
    target = "x"

    def __init__(self, client: httpx.AsyncClient, creds: dict[str, str], url: str = X_POST_URL):
        self.client, self.creds, self.url = client, creds, url

    async def post(self, text: str) -> str:
        resp = await self.client.post(self.url, json={"text": text},
                                      headers={"Authorization": oauth1_header("POST", self.url, self.creds)})
        if resp.status_code >= 400:
            raise RuntimeError(f"X API {resp.status_code}: {resp.text[:300]}")
        return str(resp.json().get("data", {}).get("id", ""))


# --- Planner ---

def ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _num(v: float | None) -> str:
    if v is None:
        return "?"
    return f"{v:g}" if v == int(v) else f"{v:.2f}"


def _places(n: int) -> str:
    return "place" if abs(n) == 1 else "places"


@dataclass(frozen=True)
class Post:
    kind: str
    team_number: str
    text: str


@dataclass
class _Seen:
    team: TeamScore
    moved_at: datetime | None = None    # when play time last moved
    announced: bool = False
    hour_left: bool = False
    time_up: bool = False
    done_places: tuple[int, int] | None = None  # (national, state) last reported once done
    place_posted_at: datetime | None = None


class PostPlanner:
    def __init__(self, tz: tzinfo):
        self.tz = tz
        self._seen: dict[str, _Seen] = {}
        self._primed = False

    def _name(self, t: TeamScore, schools: dict[str, str]) -> str:
        school = schools.get(t.team_number, "")
        return f"{school} ({t.team_number})" if school else f"Team {t.team_number}"

    def observe(self, watched: Iterable[TeamScore], schools: dict[str, str], settings: PostSettings,
                at: datetime) -> list[Post]:
        """Messages for this board (watched teams only).

        The first board after a start only primes the state: whatever has already
        happened (playing, an hour left, time up) is marked as announced.
        """
        out: list[Post] = []
        primed, self._primed = self._primed, True
        for t in watched:
            pt = t.play_time or 0
            prev = self._seen.get(t.team_number)
            fresh = prev is None or pt < (prev.team.play_time or 0)  # first sighting or a new round
            if fresh:
                seen = self._seen[t.team_number] = _Seen(t, moved_at=at)
                if not primed:
                    seen.announced = pt > 0
                    seen.hour_left = pt >= ROUND_SECONDS - 3600
                    seen.time_up = pt >= ROUND_SECONDS - 60
            else:
                seen = prev
                if pt > (prev.team.play_time or 0):
                    seen.moved_at = at
            if pt > 0 and not seen.announced:
                seen.announced = True
                out.append(self._on_board(t, schools, at))
            if pt >= ROUND_SECONDS - 3600 and not seen.hour_left:
                seen.hour_left = True
                if pt < ROUND_SECONDS - 60:
                    out.append(Post("hour_left", t.team_number,
                                    f"Less than one hour remaining for {self._name(t, schools)}."))
            if pt >= ROUND_SECONDS - 60 and not seen.time_up:
                seen.time_up = True
                out.append(Post("time_up", t.team_number,
                                f"Time is up for {self._name(t, schools)}: {_num(t.score)} points, "
                                f"{ordinal(t.place_state_division)} in {t.location}, "
                                f"{ordinal(t.place_division)} nationally. Places can still change "
                                f"as other teams finish."))
            done = seen.time_up or (pt > 0 and seen.moved_at is not None and at - seen.moved_at >= DONE_AFTER)
            if not fresh and not done:
                change = self._change(prev.team, t, schools, settings)
                if change is not None:
                    out.append(change)
            if done:
                places = (t.place_division, t.place_state_division)
                if seen.done_places is None:  # just finished: report later moves from here
                    seen.done_places, seen.place_posted_at = places, at
                elif places != seen.done_places and \
                        at - seen.place_posted_at >= timedelta(minutes=settings.place_every_minutes):
                    out.append(self._place(seen.done_places, t, schools))
                    seen.done_places, seen.place_posted_at = places, at
            seen.team = t
        return [p for p in out if p.kind in settings.kinds]

    def _on_board(self, t: TeamScore, schools: dict[str, str], at: datetime) -> Post:
        local = at.astimezone(self.tz)
        clock = f"{local.hour % 12 or 12}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'}"
        return Post("on_board", t.team_number,
                    f"{self._name(t, schools)} is on the board at {clock} with {_num(t.score)} points, "
                    f"{ordinal(t.place_state_division)} in {t.location} ({t.division}).")

    def _place(self, before: tuple[int, int], t: TeamScore, schools: dict[str, str]) -> Post:
        def moved(old: int, new: int) -> str:
            return f"up {old - new}" if new < old else f"down {new - old}" if new > old else "unchanged"
        return Post("place", t.team_number,
                    f"Standings update for {self._name(t, schools)} (finished, {_num(t.score)} points): "
                    f"{ordinal(t.place_state_division)} in {t.location} ({moved(before[1], t.place_state_division)}), "
                    f"{ordinal(t.place_division)} nationally ({moved(before[0], t.place_division)}).")

    def _change(self, before: TeamScore, after: TeamScore, schools: dict[str, str],
                settings: PostSettings) -> Post | None:
        if (after.play_time or 0) < settings.change_after_hours * 3600:
            return None
        ds = round((after.score or 0) - (before.score or 0), 2)
        dn = before.place_division - after.place_division
        dst = before.place_state_division - after.place_state_division
        if not (ds or dn or dst):
            return None
        parts = []  # most significant first, as the legacy bot did
        items = sorted([("score", ds), ("national", dn), ("state", dst)], key=lambda kv: abs(kv[1]), reverse=True)
        for name, amount in items:
            if name == "score":
                parts.append(f"+{_num(ds)} points to {_num(after.score)}." if ds > 0 else
                             f"{_num(ds)} points, down to {_num(after.score)}." if ds < 0 else
                             f"Score unchanged ({_num(after.score)}).")
            elif name == "national":
                n = ordinal(after.place_division)
                parts.append(f"Up {dn} {_places(dn)} nationally (now {n})." if dn > 0 else
                             f"Down {-dn} {_places(dn)} nationally (now {n})." if dn < 0 else
                             f"Still {n} nationally.")
            else:
                n = ordinal(after.place_state_division)
                parts.append(f"Up {dst} {_places(dst)} in {after.location} (now {n})." if dst > 0 else
                             f"Down {-dst} {_places(dst)} in {after.location} (now {n})." if dst < 0 else
                             f"Still {n} in {after.location}.")
        return Post("change", after.team_number, f"{self._name(after, schools)}: " + " ".join(parts))


# --- Sending ---

@dataclass(frozen=True)
class PostRecord:
    at: datetime
    kind: str
    team_number: str
    text: str
    target: str
    status: str
    detail: str


class Poster:
    def __init__(self, store: SnapshotStore, board: BoardConfig, box: SecretBox, client: httpx.AsyncClient,
                 tz: tzinfo, notifier_factory=None):
        self.store, self.board, self.box, self.client = store, board, box, client
        self.planner = PostPlanner(tz)
        self.credentials = Credentials(board, box)
        self._factory = notifier_factory  # tests: settings -> Notifier
        metadata.create_all(store.engine, tables=[posts])

    def settings(self) -> PostSettings:
        return PostSettings.load(self.board)

    def notifier(self, settings: PostSettings) -> Notifier | None:
        if self._factory is not None:
            return self._factory(settings)
        if not settings.enabled:
            return None
        if settings.mode == "dry_run":
            return LogNotifier()
        if settings.mode == "x":
            creds = self.credentials.get()
            return XNotifier(self.client, creds) if creds else None
        return None

    def _record(self, post: Post, text: str, target: str, status: str, detail: str) -> None:
        with self.store.lock, self.store.engine.begin() as conn:
            conn.execute(insert(posts).values(at=_to_db(datetime.now(UTC)), kind=post.kind,
                                              team_number=post.team_number, text=text, target=target,
                                              status=status, detail=detail[:1000]))

    def _sent_since(self, since: datetime) -> int:
        with self.store.lock, self.store.engine.connect() as conn:
            return conn.scalar(select(func.count()).select_from(posts)
                               .where(posts.c.at >= _to_db(since), posts.c.status == "sent",
                                      posts.c.target == "x")) or 0

    def recent(self, limit: int = 25) -> list[PostRecord]:
        with self.store.lock, self.store.engine.connect() as conn:
            rows = conn.execute(select(posts).order_by(posts.c.at.desc(), posts.c.id.desc()).limit(limit)).all()
        return [PostRecord(_from_db(r.at), r.kind, r.team_number, r.text, r.target, r.status, r.detail)
                for r in rows]

    def compose(self, text: str, settings: PostSettings) -> str:
        full = f"{text} {settings.footer}".strip() if settings.footer else text
        return full if len(full) <= X_MAX_CHARS else full[:X_MAX_CHARS - 1] + "…"

    async def send(self, post: Post, settings: PostSettings | None = None, *, limits: bool = True) -> str:
        """Send one post (respecting the limits); returns its status."""
        import asyncio
        settings = settings or self.settings()
        notifier = self.notifier(settings)
        text = self.compose(post.text, settings)
        if notifier is None:
            if settings.enabled and settings.mode == "x":
                await asyncio.to_thread(self._record, post, text, "x", "skipped", "X credentials are incomplete")
                return "skipped"
            return "off"
        if limits and notifier.target == "x":
            now = datetime.now(UTC)
            hour = await asyncio.to_thread(self._sent_since, now - timedelta(hours=1))
            day = await asyncio.to_thread(self._sent_since, now - timedelta(days=1))
            if hour >= settings.per_hour or day >= settings.per_day:
                why = f"limit reached ({hour}/{settings.per_hour} this hour, {day}/{settings.per_day} today)"
                await asyncio.to_thread(self._record, post, text, notifier.target, "skipped", why)
                return "skipped"
        try:
            detail = await notifier.post(text)
            status = "sent"
        except Exception as e:
            log.warning("Post failed: %s", e)
            detail, status = str(e), "failed"
        await asyncio.to_thread(self._record, post, text, notifier.target, status, detail)
        return status

    async def board_changed(self, teams: Iterable[TeamScore], at: datetime) -> list[str]:
        """Called by the poller after each board change (with the collected teams)."""
        settings = self.settings()
        watch = set(self.board.watchlist)
        watched = [t for t in teams if t.team_number in watch]
        planned = self.planner.observe(watched, self.board.schools, settings, at)
        if not settings.enabled:
            return []
        return [await self.send(p, settings) for p in planned]
