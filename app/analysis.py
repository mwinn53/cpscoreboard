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
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass, field

from .analysis_store import DISTRICT, EMS, AnalysisStore, ImageRow, RoundInfo, TeamRow
from .posting import ordinal

ROUND_SECONDS = 6 * 3600


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


@dataclass
class ImageSummary:
    name: str
    total_items: int | None
    attempted: int
    completion: Describe
    score: Describe


@dataclass
class TeamResult:
    team: TeamRow
    percentile: float
    images: dict[str, ImageRow]
    completion: dict[str, float | None]


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
    findings: list[str] = field(default_factory=list)


def image_totals(images: list[ImageRow]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for i in images:
        if i.found is not None and i.remaining is not None:
            totals[i.image] = max(totals.get(i.image, 0), i.found + i.remaining)
    return totals


def round_report(store: AnalysisStore, info: RoundInfo, state: str = "GA") -> RoundReport:
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
            describe(i.score for i in rows)))

    ems = [TeamResult(t, percentile(t.score, scores), by_team[t.team_number],
                      {n: completion(t.team_number, n) for n in names}) for t in groups["ems"]]
    in_state = groups["state"]
    leader = in_state[0].score if in_state else 0.0
    state_table = [(t, (in_state[i - 1].score - t.score) if i else 0.0, leader - t.score)
                   for i, t in enumerate(in_state)]
    minutes = [t.play_time / 60 for t in teams if t.play_time]
    report = RoundReport(
        info=info, state=state, counts={k: len(v) for k, v in groups.items()},
        score={k: describe(t.score for t in v) for k, v in groups.items()},
        play_time=describe(minutes), over_limit=sum(1 for t in teams if (t.play_time or 0) > ROUND_SECONDS),
        images=image_summaries, ems=ems, top=teams[:25], state_table=state_table,
        has_challenge=any(t.challenge_1 for t in teams))
    report.findings = findings(report)
    return report


def _n(v: float | None, digits: int = 0) -> str:
    if v is None:
        return "–"
    return f"{v:.{digits}f}" if digits else f"{v:g}" if v == int(v) else f"{v:.1f}"


def findings(r: RoundReport) -> list[str]:
    """Plain, factual statements from the numbers (coaches add interpretation in the notes)."""
    out = []
    nat, st = r.score["national"], r.score["state"]
    if nat.n:
        out.append(f"{nat.n} teams competed in {r.info.division}; the median score was {_n(nat.median)} "
                   f"(middle half {_n(nat.q1)}–{_n(nat.q3)}).")
    if st.n and nat.median is not None:
        rel = "above" if st.median > nat.median else "below" if st.median < nat.median else "equal to"
        # As in the legacy report: if the national median falls inside the state's middle half (IQR),
        # the difference isn't meaningful.
        inside = st.n > 1 and st.q1 <= nat.median <= st.q3
        out.append(f"{r.state}'s median ({_n(st.median)}, {st.n} teams) was {rel} the national median"
                   + ("; the national median is inside the state's middle half, so the difference isn't meaningful."
                      if inside else "; the national median is outside the state's middle half."))
    for res in r.ems:
        t = res.team
        name = f" ({t.name})" if t.name else ""
        places = ", ".join(p for p in (
            f"{ordinal(t.place_division)} nationally" if t.place_division else "",
            f"{ordinal(t.place_state_division)} in {t.location}" if t.place_state_division else "") if p)
        out.append(f"{t.team_number}{name}: {_n(t.score, 2) if t.score % 1 else _n(t.score)} points"
                   f"{', ' + places if places else ''}; outscored {res.percentile:.0f}% of the division.")
    if st.n >= 4 and st.iqr is not None:  # outliers within the state, by the 1.5 x IQR rule (box-plot whiskers)
        hi, lo = st.q3 + 1.5 * st.iqr, st.q1 - 1.5 * st.iqr
        for res in r.ems:
            if res.team.score > hi:
                out.append(f"{res.team.team_number} was an upper outlier among {r.state} teams.")
            elif res.team.score < lo:
                out.append(f"{res.team.team_number} was a lower outlier among {r.state} teams.")
    for img in r.images:
        if img.completion.n and r.ems:
            above = [res.team.team_number for res in r.ems
                     if (res.completion.get(img.name) or 0) > (img.completion.median or 0)]
            out.append(f"{img.name}: median completion {_pct(img.completion.median)}; "
                       f"{len(above)} of {len(r.ems)} of our teams were above it.")
    if r.over_limit:
        out.append(f"{r.over_limit} teams played past the 6-hour limit.")
    return out


def _pct(v: float | None) -> str:
    return "–" if v is None else f"{100 * v:.0f}%"
