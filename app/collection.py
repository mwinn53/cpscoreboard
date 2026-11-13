"""Which teams the app keeps (and, from milestone 3, stores).

Filtering happens *after* places are computed on the full board, so a kept team's
overall/division/state places are still its real places. Empty criteria keep
everything. Matching is case-insensitive. Watched teams are always kept, even
outside the criteria, so a watchlist never silently loses a team.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .scraper import TeamScore


def _items(value: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(v.strip() for v in value.split(",") if v.strip()))


@dataclass(frozen=True)
class CollectionFilter:
    locations: frozenset[str] = frozenset()    # casefolded, for matching
    divisions: frozenset[str] = frozenset()
    always_keep: frozenset[str] = frozenset()  # team numbers
    labels: tuple[tuple[str, ...], tuple[str, ...]] = ((), ())  # as configured, for display

    @classmethod
    def from_strings(cls, locations: str = "", divisions: str = "",
                     always_keep: Iterable[str] = ()) -> CollectionFilter:
        locs, divs = _items(locations), _items(divisions)
        return cls(frozenset(v.casefold() for v in locs), frozenset(v.casefold() for v in divs),
                   frozenset(always_keep), (locs, divs))

    @property
    def active(self) -> bool:
        return bool(self.locations or self.divisions)

    def matches(self, team: TeamScore) -> bool:
        if team.team_number in self.always_keep:
            return True
        if self.locations and team.location.casefold() not in self.locations:
            return False
        if self.divisions and team.division.casefold() not in self.divisions:
            return False
        return True

    def apply(self, teams: list[TeamScore]) -> list[TeamScore]:
        if not self.active:
            return teams
        return [t for t in teams if self.matches(t)]

    def describe(self) -> str:
        if not self.active:
            return "all teams"
        locs, divs = self.labels
        parts = []
        if locs:
            parts.append("locations " + ", ".join(locs))
        if divs:
            parts.append("divisions " + ", ".join(divs))
        return "; ".join(parts)
