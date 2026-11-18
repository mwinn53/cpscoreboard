"""Pace against the top quarter (#77): where in the round our teams fall behind.

The **top quarter** is the teams with a 5-minute history whose final score is at or
above the field's upper quartile (the same q3 the points-within-reach breakdown uses
per image). Their median and middle half are drawn by minutes since each team's own
start, as the field's are on the in-round progress chart.

For each of our teams, the **gap** at each hour is the top quarter's median minus our
score then; the hour where it **grew** the most is where we lost the most ground. Per
image, the minutes to the first points and to half of the image's final score, ours
against the top quarter's median, show a slow start on a particular image.

Built from the same curves as ``analysis.progress``; nothing here without a 5-minute
history (legacy rounds with only totals get the team curves but no per-image pace).
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from .analysis_legacy import TOTAL

MIN_TOP = 3        # top-quarter teams with a history needed for a curve


@dataclass
class TeamPace:
    team: str                    # team number
    label: str
    gap: list[float]             # top quarter's median minus ours, at each hour 0..H
    worst_hour: int | None       # the hour (1 = the first) in which the gap grew the most
    worst_growth: float          # points the gap grew in that hour

    @property
    def final_gap(self) -> float:
        return self.gap[-1] if self.gap else 0.0

    @property
    def first_hour_share(self) -> float | None:
        """The share of the final gap that opened in the first hour (when we finished behind)."""
        if self.final_gap <= 0 or len(self.gap) < 2:
            return None
        return max(0.0, self.gap[1] - self.gap[0]) / self.final_gap


@dataclass
class ImagePace:
    image: str
    top_first: float | None      # the top quarter's median minutes to its first points on the image
    top_half: float | None       # ... and to half of its final score there
    ours: dict[str, tuple[float | None, float | None]] = field(default_factory=dict)  # team -> (first, half)

    def our_median(self, k: int) -> float | None:
        vals = [v[k] for v in self.ours.values() if v[k] is not None]
        return statistics.median(vals) if vals else None


@dataclass
class Pace:
    top_n: int                   # top-quarter teams with a history
    cut: float                   # the final score that puts a team in the top quarter
    minutes: list[int]
    q1: list[float | None]
    median: list[float | None]
    q3: list[float | None]
    teams: list[TeamPace]
    images: list[ImagePace]

    def hourly_median(self) -> list[float]:
        return [v or 0.0 for m, v in zip(self.minutes, self.median) if m % 60 == 0]


def image_marks(timeline: list[tuple[str, str, datetime, float]]) -> dict[str, dict[str, tuple[float | None, float | None]]]:
    """Per team and image: minutes (since the team's first check) to its first points and to half its final score."""
    rows: dict[str, list[tuple[datetime, str, float]]] = defaultdict(list)
    for team, image, at, score in timeline:
        rows[team].append((at, image, score))
    out: dict[str, dict[str, tuple[float | None, float | None]]] = {}
    for team, pts in rows.items():
        pts.sort(key=lambda p: p[0])
        start = pts[0][0]
        by_image: dict[str, list[tuple[float, float]]] = defaultdict(list)
        for at, image, score in pts:
            if image != TOTAL:
                by_image[image].append(((at - start).total_seconds() / 60, score))
        marks = {}
        for image, series in by_image.items():
            final = series[-1][1]
            if final <= 0:
                continue
            first = next(m for m, v in series if v > 0)
            half = next(m for m, v in series if v >= final / 2)
            marks[image] = (first, half)
        if marks:
            out[team] = marks
    return out


def _median(vals) -> float | None:
    vals = [v for v in vals if v is not None]
    return statistics.median(vals) if vals else None


def pace(r, curves: dict[str, list[tuple[float, float]]],
         timeline: list[tuple[str, str, datetime, float]]) -> Pace | None:
    from .analysis import describe, value_at
    p = r.progress
    if not p or not curves:
        return None
    final = {t.team_number: t.score for t in r.teams}
    scores = [final.get(team, c[-1][1] if c else 0.0) for team, c in curves.items()]
    cut = describe(scores).q3
    if cut is None:
        return None
    top = [team for team, s in zip(curves, scores) if s >= cut]
    if len(top) < MIN_TOP:
        return None
    stats = [describe(value_at(curves[t], m) for t in top) for m in p.minutes]
    hours = [k for k, m in enumerate(p.minutes) if m % 60 == 0]
    teams = []
    for res in r.ems:
        c = curves.get(res.team.team_number)
        if not c:
            continue
        gap = [stats[k].median - value_at(c, p.minutes[k]) for k in hours]
        growth = [(gap[h] - gap[h - 1], h) for h in range(1, len(gap))]
        worst = max(growth, key=lambda g: g[0], default=(0.0, None))   # ties: the earliest hour
        teams.append(TeamPace(res.team.team_number, res.label, gap,
                              worst[1] if worst[0] > 0 else None, max(worst[0], 0.0)))
    marks = image_marks(timeline)
    images = []
    for name in sorted({i for m in marks.values() for i in m}):
        top_marks = [marks[t][name] for t in top if name in marks.get(t, {})]
        if len(top_marks) < MIN_TOP:
            continue
        ours = {t.team: marks[t.team][name] for t in teams if name in marks.get(t.team, {})}
        images.append(ImagePace(name, _median(m[0] for m in top_marks), _median(m[1] for m in top_marks), ours))
    return Pace(len(top), cut, p.minutes, [s.q1 for s in stats], [s.median for s in stats], [s.q3 for s in stats],
                teams, images)
