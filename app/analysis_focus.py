"""Where the points went: what a round report says about where to focus practice.

Three views of our teams' per-image results, all built from data the collector
already has (no extra scoreboard requests):

* **Points within reach** (#76): for each of our teams, the points to the next
  place in the state and to the state's top quarter, and where they could come
  from. An image's **points per item** is the median of score ÷ items found among
  teams with no penalties on it that found more than our team did (so it's the
  value of the items we'd be adding); the items **within reach** are those the
  field's top quarter found on that image and we didn't. "2 more items on Server
  ≈ +8 points ≈ +3 places" combines the two.
* **Strengths and weaknesses** (#75): a team's completion percentile on each
  image (among the teams that attempted it) against its overall percentile, so a
  strong team's weak image shows even when it beat most of the field there.
* **Penalties** (#78): our penalty rate per image against the rest of the field,
  with Fisher's exact test (our 3–4 teams are a small sample, so it seldom reaches
  significance), and the points lost to penalties, estimated as items found ×
  points per item − score.

All of it is an estimate: items on one image aren't worth exactly the same, and a
team can't always find the items another team did. The page says so.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

from scipy import stats as st

from .analysis import RoundReport, TeamResult, percentile
from .analysis_store import ImageRow, TeamRow
from .posting import ordinal

GAP = 20.0        # percentile points between an image and the overall result worth highlighting
MIN_RATE_ROWS = 5  # clean rows needed for an image's points per item
CISCO = "Cisco"


# --- points per item ---

def _ratios(rows: list[ImageRow], more_than: int = -1) -> list[float]:
    return [r.score / r.found for r in rows
            if r.found and r.found > more_than and not r.penalties and r.score is not None and r.score > 0]


def points_per_item(rows: list[ImageRow], more_than: int = -1) -> float | None:
    """The median points per item among teams with no penalties (that found more than ``more_than`` items)."""
    v = _ratios(rows, more_than)
    if len(v) < MIN_RATE_ROWS:
        v = _ratios(rows)
    return statistics.median(v) if v else None


def top_quarter_found(rows: list[ImageRow]) -> float | None:
    found = sorted(r.found for r in rows if r.found is not None)
    if len(found) < 4:
        return None
    return statistics.quantiles(found, n=4, method="inclusive")[2]


def penalty_points(row: ImageRow, rate: float | None) -> float:
    """Points a row likely lost to penalties: what its items are worth, less what it scored."""
    if not row.penalties or not row.found or rate is None or row.score is None:
        return 0.0
    return max(0.0, row.found * rate - row.score)


# --- points within reach (#76) ---

@dataclass
class Source:
    """Points a team could plausibly have added on one image."""
    image: str
    items: int                 # more items, up to what the top quarter found
    per_item: float | None
    points: float              # ≈ items × points per item
    penalty: float             # ≈ points lost to penalties there
    places_state: int = 0      # places those points (items + penalties) would gain
    places_national: int = 0

    @property
    def total(self) -> float:
        return self.points + self.penalty


@dataclass
class Target:
    label: str                 # "3rd in GA", "GA's top quarter"
    score: float
    gap: float                 # points to reach it
    plan: list[tuple[str, str, float]]   # (image, "N items" or "no penalties", points), cheapest first
    reachable: bool            # within reach on these images


@dataclass
class TeamGap:
    result: TeamResult
    sources: list[Source]      # most points first
    targets: list[Target]

    @property
    def label(self) -> str:
        return self.result.label

    @property
    def within_reach(self) -> float:
        return sum(s.total for s in self.sources)


def _places(score: float, gain: float, others: list[float]) -> int:
    return sum(1 for s in others if score < s <= score + gain)


def _plan(sources: list[Source], gap: float) -> tuple[list[tuple[str, str, float]], bool]:
    """Fewest changes to make up ``gap``: penalties first (no new items needed), then the richest items."""
    steps: list[tuple[str, str, float]] = []
    left = gap
    for s in sorted(sources, key=lambda s: -s.penalty):
        if left <= 0:
            break
        if s.penalty > 0.5:
            steps.append((s.image, "no penalties", s.penalty))
            left -= s.penalty
    for s in sorted((s for s in sources if s.items and s.per_item), key=lambda s: -(s.per_item or 0)):
        if left <= 0:
            break
        k = min(s.items, math.ceil(left / s.per_item))
        steps.append((s.image, f"{k} more item{'s' if k != 1 else ''}", k * s.per_item))
        left -= k * s.per_item
    return steps, left <= 0


def team_gaps(r: RoundReport) -> list[TeamGap]:
    rows_by_image: dict[str, list[ImageRow]] = {}
    for t in r.teams:
        for name, row in r.by_team.get(t.team_number, {}).items():
            rows_by_image.setdefault(name, []).append(row)
    rate = {name: points_per_item(rows) for name, rows in rows_by_image.items()}
    top = {name: top_quarter_found(rows) for name, rows in rows_by_image.items()}
    state_scores = [t.score for t in r.teams if t.location == r.state]
    national = [t.score for t in r.teams]
    out = []
    for res in r.ems:
        t = res.team
        sources = []
        for name, rows in sorted(rows_by_image.items()):
            mine = res.images.get(name)
            found = (mine.found or 0) if mine else 0
            cap = r.totals.get(name)
            reach = top[name]
            items = max(0, math.floor((min(reach, cap) if cap else reach) - found)) if reach is not None else 0
            per = points_per_item(rows, more_than=found)
            pen = penalty_points(mine, rate[name]) if mine else 0.0
            if not items and pen <= 0.5:
                continue
            s = Source(name, items, per, items * (per or 0), pen)
            s.places_state = _places(t.score, s.total, state_scores) if t.location == r.state else 0
            s.places_national = _places(t.score, s.total, national)
            sources.append(s)
        sources.sort(key=lambda s: -s.total)
        out.append(TeamGap(res, sources, _targets(r, t, sources)))
    return out


def _targets(r: RoundReport, t: TeamRow, sources: list[Source]) -> list[Target]:
    in_state = t.location == r.state
    pool = [x for x in r.teams if x.location == r.state] if in_state else r.teams
    where = r.state if in_state else "the division"
    above = [x for x in pool if x.score > t.score]
    targets = []
    if above:
        nxt = min(above, key=lambda x: x.score)
        place = (nxt.place_state_division if in_state else nxt.place_division) or len(above)
        targets.append((f"{ordinal(place)} in {where}", nxt.score))
    if len(pool) >= 8:
        cut = sorted((x.score for x in pool), reverse=True)[max(len(pool) // 4 - 1, 0)]
        if cut > t.score and (not targets or cut != targets[0][1]):
            targets.append((f"{r.state}'s top quarter" if in_state else "the division's top quarter", cut))
    out = []
    for label, score in targets:
        gap = score - t.score
        plan, ok = _plan(sources, gap)
        out.append(Target(label, score, gap, plan, ok))
    return out


def cheapest(gaps: list[TeamGap]) -> tuple[str, int, float, int] | None:
    """The image where our teams had the most points within reach: (image, median items, median points, teams)."""
    by: dict[str, list[Source]] = {}
    for g in gaps:
        for s in g.sources:
            by.setdefault(s.image, []).append(s)
    if not by:
        return None
    name, rows = max(by.items(), key=lambda kv: (sum(s.total for s in kv[1]), kv[0]))
    return (name, round(statistics.median(s.items for s in rows)), statistics.median(s.total for s in rows),
            len(rows))


# --- strengths and weaknesses (#75) ---

@dataclass
class Relative:
    images: list[str]                          # columns (Cisco last when the round has it)
    rows: list[tuple[TeamResult, dict[str, tuple[float, float] | None]]]   # team -> column -> (percentile, gap)
    threshold: float = GAP

    def flagged(self) -> list[tuple[str, str, float]]:
        """(team, image, gap) beyond the threshold, the biggest first."""
        out = [(res.label, img, cell[1]) for res, cells in self.rows for img, cell in cells.items()
               if cell and abs(cell[1]) >= self.threshold]
        return sorted(out, key=lambda x: -abs(x[2]))


def image_percentiles(r: RoundReport) -> dict[str, dict[str, float]]:
    """Each team's completion percentile on each image it attempted, among the teams that attempted it."""
    comp: dict[str, dict[str, float]] = {}
    for t in r.teams:
        for name in r.by_team.get(t.team_number, {}):
            c = r.completion(t.team_number, name)
            if c is not None:
                comp.setdefault(name, {})[t.team_number] = c
    return {name: {team: percentile(c, list(v.values())) for team, c in v.items()} for name, v in comp.items()}


def relative(r: RoundReport, pcts: dict[str, dict[str, float]] | None = None) -> Relative | None:
    if not r.ems:
        return None
    pcts = image_percentiles(r) if pcts is None else pcts
    images = [i.name for i in r.images if i.name in pcts]
    cisco = r.has_challenge and any(res.challenge_percentile is not None for res in r.ems)
    cols = images + ([CISCO] if cisco else [])
    rows = []
    for res in r.ems:
        cells: dict[str, tuple[float, float] | None] = {}
        for img in images:
            p = pcts[img].get(res.team.team_number)
            cells[img] = (p, p - res.percentile) if p is not None else None
        if cisco:
            p = res.challenge_percentile
            cells[CISCO] = (p, p - res.percentile) if p is not None else None
        rows.append((res, cells))
    return Relative(cols, rows)


# --- penalties (#78) ---

@dataclass
class PenaltyRow:
    image: str
    ours_with: int
    ours_n: int
    field_with: int             # the rest of the division (our teams left out)
    field_n: int
    ours_mean: float
    field_mean: float
    p: float | None             # Fisher's exact test, two-sided
    ours_lost: float            # ≈ points our teams lost to penalties on this image, together
    per_item: float | None

    @property
    def ours_share(self) -> float:
        return self.ours_with / self.ours_n if self.ours_n else 0.0

    @property
    def field_share(self) -> float:
        return self.field_with / self.field_n if self.field_n else 0.0

    @property
    def higher(self) -> bool:
        return self.ours_with > 0 and self.ours_share > self.field_share


def penalties(r: RoundReport) -> list[PenaltyRow]:
    ours = {res.team.team_number for res in r.ems}
    out = []
    for img in r.images:
        rows = [r.by_team[t.team_number][img.name] for t in r.teams if img.name in r.by_team.get(t.team_number, {})]
        if not any(x.penalties is not None for x in rows):
            continue
        mine = [x for x in rows if x.team_number in ours]
        rest = [x for x in rows if x.team_number not in ours]
        if not mine or len(rest) < 5:
            continue
        ow, fw = sum(1 for x in mine if x.penalties), sum(1 for x in rest if x.penalties)
        p = None
        if ow or fw:
            p = float(st.fisher_exact([[ow, len(mine) - ow], [fw, len(rest) - fw]]).pvalue)
        rate = points_per_item(rows)
        out.append(PenaltyRow(img.name, ow, len(mine), fw, len(rest),
                              statistics.fmean(x.penalties or 0 for x in mine),
                              statistics.fmean(x.penalties or 0 for x in rest), p,
                              sum(penalty_points(x, rate) for x in mine), rate))
    return out


# --- all of it, for the report ---

@dataclass
class Focus:
    gaps: list[TeamGap] = field(default_factory=list)
    relative: Relative | None = None
    penalties: list[PenaltyRow] = field(default_factory=list)
    image_pct: dict[str, dict[str, float]] = field(default_factory=dict)   # image -> team -> percentile

    @property
    def cheapest(self):
        return cheapest(self.gaps)


def focus(r: RoundReport) -> Focus:
    pcts = image_percentiles(r)
    return Focus(team_gaps(r), relative(r, pcts), penalties(r), pcts)
