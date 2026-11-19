"""Coach-chosen comparisons (#67): teams to follow, another state, the top N, saved per division.

The choices live in ``app_settings`` under ``compare:<division>`` as JSON, so a report and the season pages
read the same ones. ``comparison()`` turns them into groups for one round's report; it is cheap and is not
cached with the report, so changing the choices shows at once.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .analysis import Describe, GroupTest, RoundReport, describe, group_test, percentile
from .analysis_store import TeamRow

KEY = "compare:{}"
MAX_TEAMS = 40
TOP_CHOICES = (0, 10, 25, 50, 100)
TEAM_RE = re.compile(r"\b\d{2}-\d{4}\b")


@dataclass
class Choices:
    teams: list[str] = field(default_factory=list)   # team numbers to follow, in the coach's order
    state: str = ""                                   # another state to compare with ("" = none)
    top: int = 25                                     # the top N nationally (0 = off)

    @property
    def empty(self) -> bool:
        return not self.teams and not self.state


def parse_teams(text: str) -> list[str]:
    """Team numbers (19-1234) from free text, in order, without repeats, at most MAX_TEAMS."""
    out: list[str] = []
    for n in TEAM_RE.findall(text or ""):
        if n not in out:
            out.append(n)
    return out[:MAX_TEAMS]


def load(board, division: str) -> Choices:
    raw = board.get_value(KEY.format(division)) if division else ""
    try:
        d = json.loads(raw) if raw else {}
    except ValueError:
        d = {}
    top = d.get("top", 25)
    return Choices(parse_teams(" ".join(d.get("teams", []))), str(d.get("state", "")).upper()[:2],
                   top if top in TOP_CHOICES else 25)


def save(board, division: str, choices: Choices) -> None:
    board.set_value(KEY.format(division), json.dumps(
        {"teams": choices.teams[:MAX_TEAMS], "state": choices.state, "top": choices.top}))


@dataclass
class Group:
    key: str                    # national, state, other, top, follow, ours
    label: str
    teams: list[TeamRow]
    score: Describe
    test: GroupTest | None      # against our state's teams


@dataclass
class Followed:
    team: TeamRow
    percentile: float
    state_place: int | None


@dataclass
class Comparison:
    choices: Choices
    groups: list[Group]
    followed: list[Followed]
    missing: list[str]          # followed teams not in this data set
    other_state: str            # the chosen state when it has teams here (and isn't the state read for)


def comparison(r: RoundReport, ch: Choices) -> Comparison:
    by_number = {t.team_number: t for t in r.teams}
    scores = [t.score for t in r.teams]
    state_teams = [t for t in r.teams if t.location == r.state]
    state_scores = [t.score for t in state_teams]
    other = ch.state if ch.state and ch.state != r.state and any(t.location == ch.state for t in r.teams) else ""
    follow = [by_number[n] for n in ch.teams if n in by_number]
    rows: list[tuple[str, str, list[TeamRow]]] = [("national", "Nationally", r.teams), ("state", r.state, state_teams)]
    if other:
        rows.append(("other", other, [t for t in r.teams if t.location == other]))
    if ch.top:
        rows.append(("top", f"Top {ch.top} nationally", r.teams[:ch.top]))
    if follow:
        rows.append(("follow", "Teams we follow", follow))
    ours = [res.team for res in r.ems]
    if ours:
        rows.append(("ours", "Our teams", ours))
    groups = []
    for key, label, teams in rows:
        test = None
        if key not in ("national", "state") and len(teams) > 1 and len(state_scores) > 1:
            test = group_test(label, [t.score for t in teams], r.state, state_scores)
        groups.append(Group(key, label, teams, describe(t.score for t in teams), test))
    place: dict[str, int] = {}
    seen: dict[str, int] = {}
    for t in r.teams:                       # place within the team's own state, by national order
        seen[t.location] = seen.get(t.location, 0) + 1
        place[t.team_number] = t.place_state_division or seen[t.location]
    followed = [Followed(t, percentile(t.score, scores), place.get(t.team_number)) for t in follow]
    return Comparison(ch, groups, followed, [n for n in ch.teams if n not in by_number], other)
