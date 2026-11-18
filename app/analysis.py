"""Statistics for a round sample: the numbers behind the Analysis tab's round report.

Groups, as in the legacy R report:

* **national**: every team in the sample (one division);
* **state**: teams in the board's default state (Georgia);
* **district**: the district schools' teams plus ours;
* **ems**: our teams (the watchlist; in legacy files, our named teams).

Images are compared by **completion** (found ÷ the image's total items, where an
image's total is the largest found + remaining any team saw) because rounds and
images have different numbers of items. A team's **percentile** is the share of the
division it outscored, which puts rounds of different difficulty on one scale.

Beyond the R report, a round also gets **in-round progress**: each team's total
score by minutes since its own start (teams start at different times across the
weekend), with the field's median and middle half at each point, and the pace of
the top quarter (app/analysis_pace.py).

The narrative is written from these numbers (app/analysis_narrative.py), and
``round_summary`` boils a report down to what the season and round comparisons
need (app/analysis_compare.py). Reports are cached per sample revision.
"""

from __future__ import annotations

import bisect
import math
import statistics
import threading
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from . import analysis_stats as stats
from .analysis_legacy import TOTAL
from .analysis_store import DISTRICT, EMS, AnalysisStore, ImageRow, RoundInfo, TeamRow

ROUND_MINUTES = 360    # the legacy seasons' limit; CP-19 rounds are 4 hours (see time_limit_minutes)
STEP = 10              # progress: a point every 10 minutes of a team's time
FAMILIES = ("Windows", "Windows Server", "Linux", "Other")


@dataclass(frozen=True)
class Describe:
    n: int
    mean: float | None = None
    sd: float | None = None
    median: float | None = None
    q1: float | None = None
    q3: float | None = None
    min: float | None = None
    max: float | None = None

    @property
    def iqr(self) -> float | None:
        return None if self.q1 is None else self.q3 - self.q1

    def whiskers(self, values) -> tuple[float, float] | None:
        """Box-plot whiskers: the furthest values within 1.5 × IQR of the box."""
        if self.n == 0:
            return None
        lo, hi = self.q1 - 1.5 * self.iqr, self.q3 + 1.5 * self.iqr
        inside = [v for v in values if v is not None and lo <= v <= hi]
        return (min(inside), max(inside)) if inside else (self.q1, self.q3)


def describe(values) -> Describe:
    v = sorted(x for x in values if x is not None and not (isinstance(x, float) and math.isnan(x)))
    if not v:
        return Describe(0)
    if len(v) == 1:
        return Describe(1, v[0], None, v[0], v[0], v[0], v[0], v[0])
    q1, _, q3 = statistics.quantiles(v, n=4, method="inclusive")
    return Describe(len(v), statistics.fmean(v), statistics.stdev(v), statistics.median(v), q1, q3, v[0], v[-1])


def percentile(score: float, scores: list[float]) -> float:
    """Percent of the field this score beat (ties count half)."""
    if not scores:
        return 0.0
    below = sum(1 for s in scores if s < score)
    equal = sum(1 for s in scores if s == score) - 1
    return 100.0 * (below + max(equal, 0) / 2) / max(len(scores) - 1, 1)


def time_limit_minutes(teams, season: int) -> int:
    """A round's time limit: 4 hours (CP-19 on) or 6 (the legacy seasons), from how long teams played.

    Teams play close to the limit, so a median play time of 4 h 10 min or less means a 4-hour round.
    With too few teams to tell, CP-19 and later are 4 hours."""
    played = [t.play_time / 60 for t in teams if t.play_time]
    if len(played) >= 5:
        return 240 if statistics.median(played) <= 250 else 360
    return 240 if season >= 19 else 360


def image_family(name: str) -> str:
    n = name.lower()
    if "server" in n:
        return "Windows Server"
    if n.startswith("win"):
        return "Windows"
    if any(k in n for k in ("ubuntu", "debian", "linux", "mint", "fedora", "centos", "rhel", "suse", "arch")):
        return "Linux"
    return "Other"


@dataclass
class ImageSummary:
    name: str
    total_items: int | None
    attempted: int
    completion: Describe
    score: Describe
    perfect: int = 0          # teams with nothing left to find

    @property
    def family(self) -> str:
        return image_family(self.name)


@dataclass
class TeamResult:
    team: TeamRow
    percentile: float
    images: dict[str, ImageRow]
    completion: dict[str, float | None]
    state_percentile: float | None = None
    challenge_percentile: float | None = None
    half_minutes: int | None = None       # minutes to half its final score
    hourly: dict[int, float] = field(default_factory=dict)   # hour -> percentile of the field at that point

    @property
    def label(self) -> str:
        return f"{self.team.team_number} ({self.team.name})" if self.team.name else self.team.team_number


@dataclass
class StateStat:
    state: str
    n: int
    score: Describe
    values: list[float]


@dataclass
class Density:
    states: list[StateStat]            # highest median first
    teams: Describe                    # teams per state
    medians: Describe                  # the states' median scores
    r: float | None                    # teams per state vs median score (rank correlation)
    rank: int | None                   # our state's place by median (1 = highest)
    bands: list[tuple[int, int, float | None, int]]  # (fewest, most teams, median of medians, states) by size
    test: stats.Correlation | None = None


@dataclass
class Attempts:
    most: int                           # the most images any team attempted
    by_count: dict[int, Describe]
    all_share: float
    fewer: int
    fewer_state: int
    fewer_places: tuple[int, int] | None


@dataclass
class TimeStats:
    above_median: Describe              # play minutes of teams above the national median score
    below_median: Describe
    r: float | None                     # play time vs score, teams that attempted every image (rank correlation)
    ours_mean: float | None
    test: stats.Correlation | None = None


@dataclass
class GroupTest:
    """Two groups compared: medians, the chance a team from ``a`` outscores one from ``b``, and a U test."""
    a: str
    b: str
    n_a: int
    n_b: int
    median_a: float | None
    median_b: float | None
    diff: tuple[float, float, float] | None     # median difference with its 95% bootstrap interval
    mw: stats.MannWhitney | None


def group_test(a_name: str, a: list[float], b_name: str, b: list[float]) -> GroupTest:
    return GroupTest(a_name, b_name, len(a), len(b), statistics.median(a) if a else None,
                     statistics.median(b) if b else None, stats.bootstrap_median_diff(a, b),
                     stats.mann_whitney(a, b))


@dataclass
class Progress:
    minutes: list[int]
    q1: list[float | None]
    median: list[float | None]
    q3: list[float | None]
    teams: int                          # teams with a timeline
    ours: list[tuple[str, list[float]]]  # (team number, total at each grid minute)
    half: Describe                      # the field's minutes to half its final score
    limit: int = ROUND_MINUTES          # the round's time limit, minutes


@dataclass
class RoundReport:
    info: RoundInfo
    state: str
    counts: dict[str, int]
    score: dict[str, Describe]          # by group
    play_time: Describe                  # minutes, national
    over_limit: int
    images: list[ImageSummary]
    ems: list[TeamResult]
    top: list[TeamRow]
    state_table: list[tuple[TeamRow, float, float]]  # team, behind the team above, behind the leader
    has_challenge: bool
    teams: list[TeamRow] = field(default_factory=list)      # every team, by national place
    by_team: dict[str, dict[str, ImageRow]] = field(default_factory=dict)
    totals: dict[str, int] = field(default_factory=dict)
    challenge: Describe = field(default_factory=lambda: Describe(0))
    challenge_attempted: int = 0
    density: Density | None = None
    attempts: Attempts | None = None
    time: TimeStats | None = None
    progress: Progress | None = None
    narrative: dict[str, list[str]] = field(default_factory=dict)
    limit: int = ROUND_MINUTES          # the round's time limit, minutes (4 or 6 hours)
    tests: dict[str, GroupTest] = field(default_factory=dict)      # "state" (vs the rest), "district" (vs the rest of the state)
    median_ci: dict[str, tuple[float, float]] = field(default_factory=dict)  # by group, 95% bootstrap
    focus: Any = None                   # where the points went (app/analysis_focus.py)
    pace: Any = None                    # pace against the top quarter (app/analysis_pace.py)

    def completion(self, team: str, image: str) -> float | None:
        row = self.by_team.get(team, {}).get(image)
        total = self.totals.get(image)
        return row.found / total if row and row.found is not None and total else None

    def images_attempted(self, t: TeamRow) -> int:
        return t.images if t.images is not None else len(self.by_team.get(t.team_number, {}))


def image_totals(images: list[ImageRow]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for i in images:
        if i.found is not None and i.remaining is not None:
            totals[i.image] = max(totals.get(i.image, 0), i.found + i.remaining)
    return totals


# --- progress ---

def team_curves(timeline: list[tuple[str, str, datetime, float]]) -> dict[str, list[tuple[float, float]]]:
    """Each team's total score by minutes since its first point (images summed, each held until it changes)."""
    rows: dict[str, list[tuple[datetime, str, float]]] = defaultdict(list)
    for team, image, at, score in timeline:
        rows[team].append((at, image, score))
    curves = {}
    for team, pts in rows.items():
        pts.sort(key=lambda p: p[0])
        start, cur, out = pts[0][0], {}, []
        for at, image, score in pts:
            if image == TOTAL:
                cur = {TOTAL: score}
            else:
                cur.pop(TOTAL, None)
                cur[image] = score
            m = (at - start).total_seconds() / 60
            if out and out[-1][0] == m:
                out[-1] = (m, sum(cur.values()))
            else:
                out.append((m, sum(cur.values())))
        curves[team] = out
    return curves


def value_at(curve: list[tuple[float, float]], minute: float) -> float:
    i = bisect.bisect_right([m for m, _ in curve], minute) - 1
    return curve[i][1] if i >= 0 else 0.0


def _half_minutes(curve: list[tuple[float, float]]) -> int | None:
    final = max((v for _, v in curve), default=0)
    if final <= 0:
        return None
    return next(round(m) for m, v in curve if v >= final / 2)


def progress(curves: dict[str, list[tuple[float, float]]], ems: list[TeamResult],
             limit: int = ROUND_MINUTES) -> Progress | None:
    if len(curves) < 3:
        return None
    GRID = list(range(0, limit + 1, STEP))  # noqa: N806
    grid = {m: [value_at(c, m) for c in curves.values()] for m in GRID}
    stats = {m: describe(v) for m, v in grid.items()}
    ours = []
    for res in ems:
        c = curves.get(res.team.team_number)
        if not c:
            continue
        ours.append((res.team.team_number, [value_at(c, m) for m in GRID]))
        res.half_minutes = _half_minutes(c)
        res.hourly = {h: percentile(value_at(c, h * 60), grid[h * 60]) for h in range(1, limit // 60 + 1)}
    return Progress(GRID, [stats[m].q1 for m in GRID], [stats[m].median for m in GRID], [stats[m].q3 for m in GRID],
                    len(curves), ours, describe(_half_minutes(c) for c in curves.values()), limit)


# --- the report ---

def _density(teams: list[TeamRow], state: str) -> Density | None:
    by_state: dict[str, list[float]] = defaultdict(list)
    for t in teams:
        by_state[t.location or "?"].append(t.score)
    if len(by_state) < 2:
        return None
    states = sorted((StateStat(s, len(v), describe(v), v) for s, v in by_state.items()),
                    key=lambda s: (-(s.score.median or 0), s.state))
    counts, medians = [s.n for s in states], [s.score.median for s in states]
    rank = next((i for i, s in enumerate(states, 1) if s.state == state), None)
    by_size = sorted(states, key=lambda s: s.n)
    k = len(by_size)
    bands = []
    if k >= 6:
        for part in (by_size[:k // 3], by_size[k // 3: 2 * k // 3], by_size[2 * k // 3:]):
            bands.append((part[0].n, part[-1].n, describe(s.score.median for s in part).median, len(part)))
    test = stats.spearman(counts, medians)
    return Density(states, describe(counts), describe(medians), test.r if test else None, rank, bands, test)


def _tests(teams: list[TeamRow], groups: dict[str, list[TeamRow]], state: str) -> dict[str, GroupTest]:
    """The state against the rest of the division; district teams against the rest of the state."""
    out = {}
    in_state = [t.score for t in groups["state"]]
    rest = [t.score for t in teams if t.location != state]
    if len(in_state) >= 5 and len(rest) >= 5:
        out["state"] = group_test(state, in_state, "the rest of the division", rest)
    district = [t.score for t in groups["state"] if t.grp in (EMS, DISTRICT)]
    others = [t.score for t in groups["state"] if t.grp not in (EMS, DISTRICT)]
    if len(district) >= 5 and len(others) >= 5:
        out["district"] = group_test("District teams", district, f"the rest of {state}", others)
    return out


def _attempts(r: RoundReport) -> Attempts | None:
    counts = {t.team_number: r.images_attempted(t) for t in r.teams}
    if not counts:
        return None
    most = max(counts.values())
    by: dict[int, list[float]] = defaultdict(list)
    for t in r.teams:
        by[counts[t.team_number]].append(t.score)
    fewer = [t for t in r.teams if counts[t.team_number] < most]
    places = [t.place_division for t in fewer if t.place_division]
    return Attempts(most, {k: describe(v) for k, v in sorted(by.items())}, len(by[most]) / len(r.teams), len(fewer),
                    sum(1 for t in fewer if t.location == r.state),
                    (min(places), max(places)) if places else None)


def _time(r: RoundReport) -> TimeStats:
    med = r.score["national"].median or 0
    most = r.attempts.most if r.attempts else 0
    played = [(t.play_time / 60, t.score) for t in r.teams if t.play_time and r.images_attempted(t) >= most]
    ours = [res.team.play_time / 60 for res in r.ems if res.team.play_time]
    test = stats.spearman([p for p, _ in played], [s for _, s in played])
    return TimeStats(describe(t.play_time / 60 for t in r.teams if t.play_time and t.score > med),
                     describe(t.play_time / 60 for t in r.teams if t.play_time and t.score <= med),
                     test.r if test else None, statistics.fmean(ours) if ours else None, test)


def round_report(store: AnalysisStore, info: RoundInfo, state: str = "GA", *, timeline: bool = True) -> RoundReport:
    teams = store.teams(info.id)
    images = store.images(info.id)
    by_team: dict[str, dict[str, ImageRow]] = defaultdict(dict)
    for i in images:
        by_team[i.team_number][i.image] = i
    totals = image_totals(images)
    names = sorted({i.image for i in images})

    teams.sort(key=lambda t: (t.place_division or 10**6, -t.score))
    scores = [t.score for t in teams]
    groups = {
        "national": teams,
        "state": [t for t in teams if t.location == state],
        "district": [t for t in teams if t.grp in (EMS, DISTRICT)],
        "ems": [t for t in teams if t.grp == EMS],
    }
    state_scores = [t.score for t in groups["state"]]
    challenge = [t.cisco for t in teams if t.cisco is not None]

    def completion(team: str, image: str) -> float | None:
        row = by_team[team].get(image)
        total = totals.get(image)
        return row.found / total if row and row.found is not None and total else None

    image_summaries = []
    for name in names:
        rows = [i for i in images if i.image == name]
        image_summaries.append(ImageSummary(
            name, totals.get(name), len(rows),
            describe(completion(t.team_number, name) for t in teams if name in by_team[t.team_number]),
            describe(i.score for i in rows),
            sum(1 for i in rows if i.remaining == 0 and (i.found or 0) > 0)))

    ems = [TeamResult(t, percentile(t.score, scores), by_team[t.team_number],
                      {n: completion(t.team_number, n) for n in names},
                      percentile(t.score, state_scores) if t.location == state and len(state_scores) > 1 else None,
                      percentile(t.cisco, challenge) if t.cisco is not None and challenge else None)
           for t in groups["ems"]]
    in_state = groups["state"]
    leader = in_state[0].score if in_state else 0.0
    state_table = [(t, (in_state[i - 1].score - t.score) if i else 0.0, leader - t.score)
                   for i, t in enumerate(in_state)]
    minutes = [t.play_time / 60 for t in teams if t.play_time]
    limit = time_limit_minutes(teams, info.season)
    report = RoundReport(
        info=info, state=state, counts={k: len(v) for k, v in groups.items()},
        score={k: describe(t.score for t in v) for k, v in groups.items()},
        play_time=describe(minutes), over_limit=sum(1 for t in teams if (t.play_time or 0) > limit * 60),
        images=image_summaries, ems=ems, top=teams[:25], state_table=state_table,
        has_challenge=any(t.cisco for t in teams), teams=teams, by_team=dict(by_team), totals=totals,
        challenge=describe(challenge), challenge_attempted=sum(1 for c in challenge if c > 0), limit=limit)
    report.density = _density(teams, state)
    report.tests = _tests(teams, groups, state)
    report.median_ci = {k: ci for k, v in groups.items() if (ci := stats.bootstrap_median([t.score for t in v]))}
    report.attempts = _attempts(report)
    report.time = _time(report)
    if timeline:
        rows = store.timeline(info.id)
        curves = team_curves(rows)
        report.progress = progress(curves, ems, limit)
        from .analysis_pace import pace
        report.pace = pace(report, curves, rows)
    from .analysis_focus import focus
    report.focus = focus(report)
    from .analysis_narrative import round_narrative
    report.narrative = round_narrative(report)
    return report


# --- cache: a report depends only on the sample revision ---

_cache: OrderedDict = OrderedDict()
_cache_lock = threading.Lock()
CACHE_SIZE = 32


def cached_report(store: AnalysisStore, info: RoundInfo, state: str, *, timeline: bool = True) -> RoundReport:
    """A report from the cache when this revision was already computed (the label and notes come from ``info``)."""
    # SQLite can reuse a deleted data set's id, so the key also has the database and the row's details.
    full = (id(store.store.engine), info.id, info.revision, info.sampled_at, info.team_count, state, True)
    keys = [full] if timeline else [full, full[:-1] + (False,)]
    with _cache_lock:
        for key in keys:
            if key in _cache:
                _cache.move_to_end(key)
                return replace(_cache[key], info=info)
    report = round_report(store, info, state, timeline=timeline)
    with _cache_lock:
        _cache[keys[-1]] = report
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    return report


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


# --- summaries for comparisons ---

@dataclass
class OurTeam:
    team_number: str
    name: str
    score: float
    percentile: float
    place_state: int | None
    place_national: int | None
    completion: dict[str, float | None]     # by image
    family: dict[str, float | None]         # by image family
    challenge: float | None
    relative: dict[str, float] = field(default_factory=dict)   # family (and Cisco) -> its percentile minus overall

    @property
    def label(self) -> str:
        return f"{self.team_number} ({self.name})" if self.name else self.team_number


@dataclass
class RoundSummary:
    info: RoundInfo
    state: str
    counts: dict[str, int]
    median: dict[str, float | None]
    top_score: float | None
    images: list[str]
    image_completion: dict[str, float | None]   # the field's median completion
    family_field: dict[str, float | None]
    family_ours: dict[str, float | None]
    state_median_pct: float | None               # where the state's median team falls nationally
    ours: list[OurTeam]
    challenge_median: float | None

    @property
    def best_pct(self) -> float | None:
        return max((o.percentile for o in self.ours), default=None)

    @property
    def median_pct(self) -> float | None:
        return statistics.median([o.percentile for o in self.ours]) if self.ours else None

    @property
    def short(self) -> str:
        return f"CP-{self.info.season} {self.info.label}"


def _family_values(completion: dict[str, float | None]) -> dict[str, float]:
    fam: dict[str, list[float]] = defaultdict(list)
    for img, c in completion.items():
        if c is not None:
            fam[image_family(img)].append(c)
    return {f: statistics.fmean(v) for f, v in fam.items()}


def _relative(r: RoundReport, res: TeamResult) -> dict[str, float]:
    """By image family (and Cisco): the team's mean image percentile there, minus its overall percentile."""
    pcts = r.focus.image_pct if r.focus else {}
    fam: dict[str, list[float]] = defaultdict(list)
    for img, by_team in pcts.items():
        if (p := by_team.get(res.team.team_number)) is not None:
            fam[image_family(img)].append(p)
    out = {f: statistics.fmean(v) - res.percentile for f, v in fam.items()}
    if r.has_challenge and res.challenge_percentile is not None:
        out["Cisco"] = res.challenge_percentile - res.percentile
    return out


def round_summary(r: RoundReport) -> RoundSummary:
    scores = [t.score for t in r.teams]
    fam_field: dict[str, list[float]] = defaultdict(list)
    for t in r.teams:
        comp = {i: r.completion(t.team_number, i) for i in r.by_team.get(t.team_number, {})}
        for f, v in _family_values(comp).items():
            fam_field[f].append(v)
    ours = [OurTeam(res.team.team_number, res.team.name, res.team.score, res.percentile,
                    res.team.place_state_division, res.team.place_division, res.completion,
                    _family_values(res.completion), res.team.cisco, _relative(r, res)) for res in r.ems]
    fam_ours: dict[str, list[float]] = defaultdict(list)
    for o in ours:
        for f, v in o.family.items():
            fam_ours[f].append(v)
    st = r.score["state"]
    return RoundSummary(
        r.info, r.state, r.counts, {k: d.median for k, d in r.score.items()}, r.score["national"].max,
        [i.name for i in r.images], {i.name: i.completion.median for i in r.images},
        {f: statistics.median(v) for f, v in fam_field.items()},
        {f: statistics.median(v) for f, v in fam_ours.items()},
        percentile(st.median, scores) if st.n and scores else None, ours,
        r.challenge.median if r.has_challenge else None)
