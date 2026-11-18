"""Advancement (#68): what it takes to advance, for the Middle School Division.

The advancement rules are the CyberPatriot 19 Rules Book's (Middle School, the same
as CP-18's); the award and tie rules are CP-18's (section 4004), not yet checked
against CP-19:

* **Semifinals (CP-19):** the top 60% of teams on the **Introductory Round and State
  Round scores combined**; teams tied at the line all advance, and a team needs more
  than zero points (CP-18);
* **AFA State Awards (CP-18):** the top three teams in each state on the same combined
  score;
* **National Finals (CP-19):** the three highest **Semifinal** scores, one team per
  school, organization or coach. The data can't see schools, but our teams share one,
  so only our best can go.

Three stages, by the report's round:

* **After the Introductory Round** (``r2``, or ``r1`` in a season without one): a
  **projection** of the State Round. Past seasons that have both an earlier round and
  a State Round give the rank correlation between the two (Spearman), the State
  Round's scale (its median over the earlier round's) and the share of teams that
  came back. With none, the projection assumes the same scale, a correlation of 0.6
  and every team returning, and the page says so. Each simulation keeps each team's
  Introductory Round rank, blurred by the correlation (a Gaussian copula), and maps it
  onto the projected State Round scores. For each of our teams: the State Round score
  that would have reached the line in each simulation (the median and the middle 80%)
  and the share of simulations in which the team's own projected score did.
* **With the State Round:** the exact combined cut line and our margins.
* **With the Semifinal:** the third-highest score, the National Finals line.

Teams that didn't play the Introductory Round aren't in the projection (they can't be
seen yet); ``played`` covers teams that won't play the State Round.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

import numpy as np
from scipy import stats as sps

from .analysis_store import AnalysisStore, TeamRow

DIVISION = "Middle School"
RULES_FROM = 18          # the first season with these rules (CP-18; CP-19 kept them)
SEMI_SHARE = 0.6         # the top 60% advance to the Semifinals
AWARDS = 3               # AFA State Awards: the top three in each state
FINALS = 3               # the National Finals: the top three Semifinal scores
INTRO_KEYS = ("r2", "r1")
STATE_KEY = "state"
SEMI_KEY = "sf"
SIMS = 2000
BAND = (10, 90)          # the likely range: the middle 80% of simulations
ASSUMED_RHO = 0.6        # with no past season to learn from
MIN_PAIRS = 30           # teams in both rounds for a past season to count


@dataclass
class Model:
    seasons: list[int]       # past seasons it learned from (empty: assumed)
    pairs: int               # teams in both rounds, over those seasons
    rho: float               # rank correlation, earlier round to State Round
    ratio: float             # State Round median ÷ the earlier round's
    played: float            # share of the earlier round's teams that played the State Round

    @property
    def assumed(self) -> bool:
        return not self.seasons


@dataclass
class Need:
    label: str
    median: float            # State Round points needed
    lo: float
    hi: float
    chance: float            # share of simulations in which the team's projected score got there
    top_share: float | None  # share of projected State Round scores at or above ``median``


@dataclass
class Projection:
    team: TeamRow
    label: str
    intro: float
    expected: float          # the team's median projected State Round score
    semis: Need
    award: Need | None       # in-state teams only


@dataclass
class Standing:
    team: TeamRow
    label: str
    intro: float | None
    state: float | None
    total: float
    margin: float            # above (+) or below (−) the line (ties advance, so 0 is in)
    state_place: int | None = None   # among the state's teams on the combined score
    award_margin: float | None = None


@dataclass
class Advancement:
    stage: str               # "projection", "state" or "semifinal"
    n: int                   # teams in the pool
    line_rank: int           # the last place that advances
    cut: float | None = None
    award_cut: float | None = None
    intro_label: str = ""
    model: Model | None = None
    projections: list[Projection] = field(default_factory=list)
    standings: list[Standing] = field(default_factory=list)


def _label(t: TeamRow) -> str:
    return f"{t.team_number} ({t.name})" if t.name else t.team_number


def _season_rounds(store: AnalysisStore, division: str) -> dict[int, dict[str, object]]:
    from .analysis_compare import pick
    out: dict[int, dict[str, object]] = {}
    for info in pick(store.rounds(division)):
        out.setdefault(info.season, {})[info.round_key] = info
    return out


def _intro(rounds: dict[str, object]):
    return next((rounds[k] for k in INTRO_KEYS if k in rounds), None)


def model(store: AnalysisStore, division: str, season: int) -> Model:
    """What past seasons say about the State Round against the round before it."""
    seasons, pairs, rhos, ratios, played = [], 0, [], [], []
    for s, rounds in sorted(_season_rounds(store, division).items()):
        prior, state = _intro(rounds), rounds.get(STATE_KEY)
        if s == season or prior is None or state is None:
            continue
        a = {t.team_number: t.score for t in store.teams(prior.id) if t.score > 0}
        b = {t.team_number: t.score for t in store.teams(state.id) if t.score > 0}
        both = [n for n in a if n in b]
        if len(both) < MIN_PAIRS:
            continue
        seasons.append(s)
        pairs += len(both)
        rho = sps.spearmanr([a[n] for n in both], [b[n] for n in both]).statistic
        rhos.append((float(rho), len(both)))
        ratios.append(statistics.median(b.values()) / statistics.median(a.values()))
        played.append(len(both) / len(a))
    if not seasons:
        return Model([], 0, ASSUMED_RHO, 1.0, 1.0)
    rho = sum(r * n for r, n in rhos) / sum(n for _, n in rhos)
    return Model(seasons, pairs, max(0.0, min(rho, 0.99)), statistics.median(ratios), statistics.median(played))


def _kth(values: np.ndarray, k: int) -> np.ndarray:
    """The k-th highest of each row (k from 1); minus infinity when a row has fewer than k."""
    if values.shape[1] < k:
        return np.full(values.shape[0], -np.inf)
    return -np.partition(-values, k - 1, axis=1)[:, k - 1]


def _need(label: str, needed: np.ndarray, own: np.ndarray, state_scores: np.ndarray) -> Need:
    needed = np.maximum(needed, 0.0)
    med = float(np.median(needed))
    lo, hi = (float(v) for v in np.percentile(needed, BAND))
    top = float(np.mean(state_scores >= med)) if state_scores.size else None
    return Need(label, med, lo, hi, float(np.mean(own >= needed)), top)


def projection(r, store: AnalysisStore) -> Advancement | None:
    pool = [t for t in r.teams if t.score > 0]
    ours = [res.team for res in r.ems if res.team.score > 0]
    n = len(pool)
    if n < 10 or not ours:
        return None
    m = model(store, r.info.division, r.info.season)
    intro = np.array([t.score for t in pool])
    index = {t.team_number: i for i, t in enumerate(pool)}
    rng = np.random.default_rng(r.info.id)
    z = sps.norm.ppf((sps.rankdata(intro) - 0.5) / n)
    zs = m.rho * z + math.sqrt(1 - m.rho ** 2) * rng.standard_normal((SIMS, n))
    quantiles = np.sort(intro) * m.ratio
    state = np.interp(sps.norm.cdf(zs), (np.arange(n) + 0.5) / n, quantiles)
    state *= rng.random((SIMS, n)) < m.played
    total = intro + state
    k = math.ceil(SEMI_SHARE * n)
    played_scores = state[state > 0]
    in_state = np.array([t.location == r.state for t in pool])
    out = []
    for t in ours:
        j = index[t.team_number]
        others = np.delete(total, j, axis=1)
        semis = _need("the Semifinals", _kth(others, k) - intro[j], state[:, j], played_scores)
        award = None
        if t.location == r.state:
            mates = np.delete(total[:, in_state], int(in_state[:j].sum()), axis=1)
            award = _need(f"a top-{AWARDS} {r.state} award", _kth(mates, AWARDS) - intro[j], state[:, j],
                          played_scores)
        out.append(Projection(t, _label(t), float(intro[j]), float(np.median(state[:, j])), semis, award))
    return Advancement("projection", n, k, model=m, projections=out)


def _standings(r, totals: dict[str, tuple[float | None, float | None]], teams: dict[str, TeamRow],
               stage: str, intro_label: str = "") -> Advancement | None:
    total = {n: (a or 0.0) + (b or 0.0) for n, (a, b) in totals.items()}
    pool = sorted((v for v in total.values() if v > 0), reverse=True)
    n = len(pool)
    if not n:
        return None
    share = SEMI_SHARE if stage == "state" else None
    k = math.ceil(share * n) if share else min(FINALS, n)
    out = Advancement(stage, n, k, cut=pool[k - 1], intro_label=intro_label)
    state = sorted((v for num, v in total.items() if v > 0 and teams[num].location == r.state), reverse=True)
    if stage == "state" and len(state) >= AWARDS:
        out.award_cut = state[AWARDS - 1]
    for res in r.ems:
        num = res.team.team_number
        if num not in total:
            continue
        mine = total[num]
        st = Standing(res.team, _label(res.team), totals[num][0], totals[num][1], mine, mine - out.cut)
        if stage == "state" and res.team.location == r.state:
            st.state_place = 1 + sum(1 for x, v in total.items()
                                     if x != num and v > mine and teams[x].location == r.state)
            st.award_margin = mine - out.award_cut if out.award_cut is not None else None
        out.standings.append(st)
    return out


def advancement(r, store: AnalysisStore) -> Advancement | None:
    """What it takes to advance, for a Middle School report from CP-18 on (None otherwise)."""
    info = r.info
    if info.division != DIVISION or info.season < RULES_FROM or not r.ems:
        return None
    rounds = _season_rounds(store, info.division).get(info.season, {})
    prior = _intro(rounds)
    if info.round_key in INTRO_KEYS and (prior is None or prior.round_key == info.round_key):
        return projection(r, store)
    if info.round_key == STATE_KEY:
        if prior is None:
            return None
        intro = {t.team_number: t for t in store.teams(prior.id)}
        teams = {t.team_number: t for t in r.teams}
        for num, t in intro.items():
            teams.setdefault(num, t)
        played = {t.team_number: t.score for t in r.teams}
        totals = {num: (intro[num].score if num in intro else None, played.get(num)) for num in teams}
        return _standings(r, totals, teams, "state", "Introductory Round")
    if info.round_key == SEMI_KEY:
        teams = {t.team_number: t for t in r.teams}
        return _standings(r, {n: (None, t.score) for n, t in teams.items()}, teams, "semifinal")
    return None
