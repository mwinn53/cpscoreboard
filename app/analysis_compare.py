"""Comparisons across data sets: a season's rounds, season over season, and any two reports.

Scores aren't comparable across rounds (different images, different numbers of
items), so comparisons use **percentiles** (the share of the division a team
outscored) and **completion** (found ÷ items, by image family: Windows, Windows
Server, Linux). Team numbers last one season, so our teams are followed by number
within a season and compared as a program across seasons.

Where a round has both preliminary and final data sets, the final one is used,
except on the two-report page, where any two can be picked (e.g. preliminary
against final).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import analysis_stats as stats
from .analysis import FAMILIES, OurTeam, RoundSummary, cached_report, round_summary
from .analysis_charts import percentile_lines
from .analysis_narrative import (history_narrative, pair_narrative, participation_context, program_narrative,
                                 season_narrative)
from .analysis_store import FINAL, AnalysisStore, RoundInfo

SHORT = {"r1": "R1", "r2": "R2", "r3": "R3", "state": "State", "st": "State", "sf": "SF", "semi": "SF",
         "semis": "SF", "nf": "Final", "final": "Final"}


def short_label(info: RoundInfo) -> str:
    return SHORT.get(info.round_key, info.label)


def pick(rounds: list[RoundInfo]) -> list[RoundInfo]:
    """One data set per round (final over preliminary), oldest first."""
    best: dict[tuple[int, str], RoundInfo] = {}
    for r in rounds:
        key = (r.season, r.round_key)
        if key not in best or (r.status == FINAL and best[key].status != FINAL):
            best[key] = r
    return sorted(best.values(), key=lambda r: r.order)


@dataclass
class ProgramStats:
    """Our teams as a program over several rounds (each team in each round counts once)."""
    n: int                                    # team-rounds
    above: int                                # how many outscored at least half the division
    median_pct: float | None
    ci: tuple[float, float] | None            # 95% bootstrap interval of the median percentile
    test: stats.SignedRank | None             # percentiles against 50 (the median team)
    trend: stats.Correlation | None           # our median team's percentile over the rounds (Kendall)
    state_test: stats.SignedRank | None       # the state's median team against 50, round by round


def program_stats(sums: list[RoundSummary]) -> ProgramStats:
    pcts = [o.percentile for s in sums for o in s.ours]
    with_ours = [s for s in sums if s.ours]
    import statistics
    return ProgramStats(
        len(pcts), sum(1 for p in pcts if p > 50), statistics.median(pcts) if pcts else None,
        stats.bootstrap_median(pcts), stats.wilcoxon_signed_rank(pcts, 50),
        stats.kendall_tau(list(range(len(with_ours))), [s.median_pct for s in with_ours]),
        stats.wilcoxon_signed_rank([s.state_median_pct for s in sums if s.state_median_pct is not None], 50))


def summaries(store: AnalysisStore, rounds: list[RoundInfo], state: str) -> list[RoundSummary]:
    return [round_summary(cached_report(store, r, state, timeline=False)) for r in rounds]


# --- a season ---

@dataclass
class SeasonView:
    season: int
    division: str
    summaries: list[RoundSummary]
    teams: list[tuple[str, dict[int, OurTeam]]]       # label -> round id -> result
    narrative: list[str]
    chart: str
    families: list[str] = field(default_factory=list)
    program: ProgramStats | None = None


def season_view(store: AnalysisStore, division: str, season: int, state: str) -> SeasonView:
    rounds = pick([r for r in store.rounds(division) if r.season == season])
    sums = summaries(store, rounds, state)
    teams: dict[str, dict[int, OurTeam]] = {}
    labels: dict[str, str] = {}
    for s in sums:
        for o in s.ours:
            teams.setdefault(o.team_number, {})[s.info.id] = o
            labels[o.team_number] = o.label
    rows = sorted(((labels[n], v) for n, v in teams.items()), key=lambda x: x[0])
    cats = [short_label(s.info) for s in sums]
    series = [(label.split(" (")[0], [v[s.info.id].percentile if s.info.id in v else None for s in sums])
              for label, v in rows]
    series.append((f"{state} median", [s.state_median_pct for s in sums]))
    slots = [f"s{i + 2}" for i in range(len(series) - 1)] + ["s1"]
    chart = percentile_lines(cats, series, label=f"CP-{season}: our teams' percentile by round",
                             slots=slots[:8]) if sums else ""
    fams = [f for f in FAMILIES if any(f in s.family_field for s in sums)]
    program = program_stats(sums)
    return SeasonView(season, division, sums, rows, season_narrative(sums) + program_narrative(program, sums), chart,
                      fams, program)


# --- season over season ---

@dataclass
class HistoryView:
    division: str
    summaries: list[RoundSummary]          # time order
    seasons: list[int]
    labels: list[str]                       # round labels, in round order
    grid: dict[tuple[str, int], RoundSummary]
    families: list[str]
    narrative: list[str]
    chart: str
    program: ProgramStats | None = None


def history_view(store: AnalysisStore, division: str, state: str) -> HistoryView:
    sums = summaries(store, pick(store.rounds(division)), state)
    seasons = sorted({s.info.season for s in sums})
    order: dict[str, tuple[int, str]] = {}
    for s in sums:
        order.setdefault(s.info.label, s.info.order[1:] + (s.info.label,))
    labels = sorted(order, key=lambda k: order[k])
    grid = {(s.info.label, s.info.season): s for s in sums}
    cats = [f"{s.info.season}·{short_label(s.info)}" for s in sums]
    chart = percentile_lines(
        cats, [("Our best", [s.best_pct for s in sums]), ("Our median", [s.median_pct for s in sums]),
               (f"{state} median", [s.state_median_pct for s in sums])],
        label="Our best and median team, and the state's median team, by round", slots=["s2", "s3", "s1"]) \
        if sums else ""
    fams = [f for f in FAMILIES if any(f in s.family_field for s in sums)]
    program = program_stats(sums)
    return HistoryView(division, sums, seasons, labels, grid, fams,
                       history_narrative(sums) + program_narrative(program, sums), chart, program)


# --- two reports ---

@dataclass
class PairView:
    a: RoundSummary
    b: RoundSummary
    matched: list[tuple[OurTeam, OurTeam]]
    images: list[str]
    families: list[str]
    narrative: list[str]
    chart: str


def pair_view(store: AnalysisStore, a: RoundInfo, b: RoundInfo, state: str) -> PairView:
    if (b.order, b.status == FINAL) < (a.order, a.status == FINAL):
        a, b = b, a
    sa, sb = summaries(store, [a, b], state)
    by_b = {o.team_number: o for o in sb.ours}
    matched = [(o, by_b[o.team_number]) for o in sa.ours if o.team_number in by_b]
    cats = [f"{sa.short} ({a.status[:5]}.)", f"{sb.short} ({b.status[:5]}.)"]
    if matched:
        series = [(ob.label.split(" (")[0], [oa.percentile, ob.percentile]) for oa, ob in matched]
        slots = [f"s{i + 2}" for i in range(len(series))]
    else:
        series = [("Our best", [sa.best_pct, sb.best_pct]), ("Our median", [sa.median_pct, sb.median_pct])]
        slots = ["s2", "s3"]
    series.append((f"{state} median", [sa.state_median_pct, sb.state_median_pct]))
    chart = percentile_lines(cats, series, label="Percentiles in the two reports", slots=(slots + ["s1"])[:8],
                             height=220)
    images = sorted(set(sa.images) | set(sb.images))
    fams = [f for f in FAMILIES if f in sa.family_field or f in sb.family_field]
    return PairView(sa, sb, matched, images, fams, pair_narrative(sa, sb, matched), chart)


def round_context(store: AnalysisStore, info: RoundInfo, state: str) -> list[str]:
    """For a report: participation against the season's previous round and the same round last season."""
    rounds = pick(store.rounds(info.division))
    current = round_summary(cached_report(store, info, state, timeline=False))
    before = [r for r in rounds if r.season == info.season and r.order < info.order]
    last = [r for r in rounds if r.season == info.season - 1 and r.round_key == info.round_key]
    prev = round_summary(cached_report(store, before[-1], state, timeline=False)) if before else None
    same = round_summary(cached_report(store, last[0], state, timeline=False)) if last else None
    return participation_context(current, prev, same)
