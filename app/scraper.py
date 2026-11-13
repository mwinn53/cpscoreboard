"""Parse the CyberPatriot scoreboard API (``/api/team/scores.php``).

Ported from ``legacy/cpscoreboard/cpsbimports.py`` without the pandas dependency.

The API returns ``{"data": [row, ...]}``, already in ranked order: the official
page renders it with DataTables ``order: []`` and numbers rows by position, so a
team's place is its position in the list (within whatever group is ranked).

Fields vary by season. Season 17 (2024) had ``adjustment``/``score_3``/``total``;
season 19 (2026) has ``tier`` but no totals. Missing fields parse as ``None``.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


class ScoreboardFormatError(ValueError):
    """The response isn't the scoreboard JSON we expect (e.g. an HTML error page)."""


@dataclass(frozen=True, slots=True)
class TeamScore:
    team_number: str
    team_id: int | None
    location: str
    division: str
    tier: str
    images: int | None
    play_time: int | None   # seconds
    score_time: int | None  # seconds into play_time when the team last scored
    ccs_score: float | None
    adjustment: float | None
    total: float | None
    code: str               # warning flags shown on the official board (e.g. "T", "M", "MT")
    place_overall: int
    place_division: int
    place_state: int           # within the state, across all divisions (legacy "StatePlace")
    place_state_division: int  # within the state and division
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @property
    def score(self) -> float:
        """The score the board is ranked by: total when published, else the CCS score."""
        if self.total is not None:
            return self.total
        return self.ccs_score or 0.0

    def to_dict(self) -> dict[str, Any]:
        d = {name: getattr(self, name) for name in self.__dataclass_fields__ if name != "raw"}
        d["score"] = self.score
        return d


def parse_hms(value: Any) -> int | None:
    """``"03:48:50"`` -> 13730 seconds. Blank or malformed values give ``None``."""
    if not value:
        return None
    parts = str(value).strip().split(":")
    if len(parts) != 3:
        return None
    try:
        h, m, s = (int(p) for p in parts)
    except ValueError:
        return None
    return h * 3600 + m * 60 + s


def _float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    f = _float(value)
    return None if f is None else int(f)


def parse_scores(payload: bytes | str | Mapping[str, Any]) -> list[TeamScore]:
    """Parse a scores.php response into ranked teams.

    Raises ``ScoreboardFormatError`` if the payload isn't scoreboard JSON.
    An empty ``data`` list (no teams on the board yet) is valid.
    """
    if isinstance(payload, (bytes, bytearray, str)):
        try:
            doc = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ScoreboardFormatError(f"response is not JSON: {e}") from e
    else:
        doc = payload

    rows = doc.get("data") if isinstance(doc, Mapping) else None
    if not isinstance(rows, list):
        raise ScoreboardFormatError("response has no 'data' list")

    places: Counter[tuple[str, ...]] = Counter()
    teams: list[TeamScore] = []
    for row in rows:
        if not isinstance(row, Mapping) or not row.get("team_number"):
            log.warning("Skipping malformed scoreboard row: %r", row)
            continue
        location = str(row.get("location") or "")
        division = str(row.get("division") or "")
        keys = {
            "overall": ("overall",),
            "division": ("division", division),
            "state": ("state", location),
            "state_division": ("state_division", location, division),
        }
        for k in keys.values():
            places[k] += 1

        teams.append(TeamScore(
            team_number=str(row["team_number"]).strip(),
            team_id=_int(row.get("team_id")),
            location=location,
            division=division,
            tier=str(row.get("tier") or ""),
            images=_int(row.get("images")),
            play_time=parse_hms(row.get("play_time")),
            score_time=parse_hms(row.get("score_time")),
            ccs_score=_float(row.get("ccs_score")),
            adjustment=_float(row.get("adjustment")),
            total=_float(row.get("total")),
            code=str(row.get("code") or ""),
            place_overall=places[keys["overall"]],
            place_division=places[keys["division"]],
            place_state=places[keys["state"]],
            place_state_division=places[keys["state_division"]],
            raw=dict(row),
        ))
    return teams


def parse_alias_file(text: str) -> dict[str, str]:
    """Parse the legacy ``lookups`` file: ``team_number,alias`` per line, ``#`` comments."""
    aliases: dict[str, str] = {}
    for lineno, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        number, _, alias = (part.strip() for part in line.partition(","))
        if not alias:
            log.warning("Alias file line %d: no alias for team %s", lineno, number)
            continue
        if number in aliases:
            log.warning("Alias file line %d: duplicate team %s; keeping %r", lineno, number, aliases[number])
            continue
        aliases[number] = alias
    return aliases


def parse_team_file(text: str) -> list[str]:
    """Parse the legacy ``team`` file: one team number per line, ``#`` comments."""
    teams: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and line not in teams:
            teams.append(line)
    return teams
