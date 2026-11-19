"""Comparisons across data sets: a season's rounds, season over season, and any two reports.

Scores aren't comparable across rounds (different images, different numbers of
items), so comparisons use **percentiles** (the share of the division a team
outscored) and **completion** (found ÷ items, by image family: Windows, Windows
Server, Linux). Team numbers last one season, so our teams are followed by number
within a season and compared as a program across seasons. The teams a coach follows
and another state to compare with (app/analysis_choices.py) get their own lines on a
season's page.

Where a round has both preliminary and final data sets, the final one is used,
except on the two-report page, where any two can be picked (e.g. preliminary
against final).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from . import analysis_stats as stats
from .analysis import FAMILIES, OurTeam, RoundSummary, cached_report, percentile, round_summary
from .analysis_choices import Choices, Followed, comparison
from .analysis_charts import percentile_lines
from .analysis_narrative import (history_narrative, pair_narrative, participation_context, program_narrative,
                                 season_narrative, strength_narrative)
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


@dataclass
class FamilyStrength:
    """An image family against our overall results, over several rounds (#75): exploratory."""
    family: str
    n: int                                    # team-rounds
    median: float                             # median gap, percentile points (negative: weaker there)
    below: int                                # team-rounds weaker there than overall
    rounds: int                               # rounds with our teams on it
    rounds_below: int                         # rounds where our median team-gap was negative
    test: stats.SignedRank | None             # the gaps against 0
    p_holm: float | None = None               # the test's p, Holm-adjusted across the families tested


def family_strength(sums: list[RoundSummary]) -> list[FamilyStrength]:
    import statistics
    out = []
    for fam in (*FAMILIES, "Cisco"):
        per_round = [[o.relative[fam] for o in s.ours if fam in o.relative] for s in sums]
        per_round = [v for v in per_round if v]
        gaps = [g for v in per_round for g in v]
        if not gaps:
            continue
        out.append(FamilyStrength(fam, len(gaps), statistics.median(gaps), sum(1 for g in gaps if g < 0),
                                  len(per_round), sum(1 for v in per_round if statistics.median(v) < 0),
                                  stats.wilcoxon_signed_rank(gaps, 0)))
    tested = [f for f in out if f.test]
    for f, p in zip(tested, stats.holm([f.test.p for f in tested])):
        f.p_holm = p
    return sorted(out, key=lambda f: f.median)


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
    strength: list[FamilyStrength] = field(default_factory=list)
    followed: list[tuple[str, dict[int, Followed]]] = field(default_factory=list)  # team -> round id -> result
    follow_missing: list[str] = field(default_factory=list)   # followed teams in none of the season's rounds
    follow_chart: str = ""
    other_state: str = ""
    other_median: dict[int, tuple[float, float]] = field(default_factory=dict)  # round id -> (median, percentile)


def _state_median(teams, state: str) -> tuple[float, float] | None:
    scores = [t.score for t in teams if t.location == state]
    if not scores:
        return None
    m = statistics.median(scores)
    return m, percentile(m, [t.score for t in teams])


def _follow(view: SeasonView, store: AnalysisStore, state: str, choices: Choices) -> None:
    """The followed teams and the chosen state's median team, round by round, and a chart of their percentiles."""
    sums = view.summaries
    found: dict[str, dict[int, Followed]] = {}
    for s in sums:
        r = cached_report(store, s.info, state, timeline=False)
        for f in comparison(r, choices).followed:
            found.setdefault(f.team.team_number, {})[s.info.id] = f
        if choices.state and choices.state != state and (m := _state_median(r.teams, choices.state)):
            view.other_median[s.info.id] = m
    view.followed = [(n, found[n]) for n in choices.teams if n in found]
    view.follow_missing = [n for n in choices.teams if n not in found]
    view.other_state = choices.state if view.other_median else ""
    if not view.followed and not view.other_state:
        return
    series = [(n, [v[s.info.id].percentile if s.info.id in v else None for s in sums]) for n, v in view.followed[:6]]
    slots = [f"s{i + 2}" for i in range(len(series))]
    if view.other_state:
        series.append((f"{view.other_state} median",
                       [view.other_median[s.info.id][1] if s.info.id in view.other_median else None for s in sums]))
        slots.append("s8")
    series.append((f"{state} median", [s.state_median_pct for s in sums]))
    slots.append("s1")
    view.follow_chart = percentile_lines([short_label(s.info) for s in sums], series, slots=slots,
                                         label=f"CP-{view.season}: the teams we follow, percentile by round")


def season_view(store: AnalysisStore, division: str, season: int, state: str,
                choices: Choices | None = None) -> SeasonView:
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
    strength = family_strength(sums)
    view = SeasonView(season, division, sums, rows,
                      season_narrative(sums) + program_narrative(program, sums) + strength_narrative(strength),
                      chart, fams, program, strength)
    if choices and sums:
        _follow(view, store, state, choices)
    return view


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
    strength: list[FamilyStrength] = field(default_factory=list)


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
    strength = family_strength(sums)
    return HistoryView(division, sums, seasons, labels, grid, fams,
                       history_narrative(sums) + program_narrative(program, sums) + strength_narrative(strength),
                       chart, program, strength)


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
