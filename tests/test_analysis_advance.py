"""What it takes to advance (app/analysis_advance.py): Middle School, CP-18 rules."""

from datetime import UTC, datetime

import pytest

from app.analysis import round_report
from app.analysis_advance import model
from app.analysis_charts import advance_chart, advance_legend
from app.analysis_store import EMS, FINAL, LEGACY, AnalysisStore, Sample, TeamRow
from app.store import SnapshotStore

T0 = datetime(2026, 11, 15, 12, tzinfo=UTC)
MS = "Middle School"
HIGH, LOW = "19-0020", "19-0080"      # our teams: well above and well below the 60% line


def _sample(season, round_key, scores, division=MS):
    """One team per score, by index: 19-0000 … ; every fourth team is in GA, and so are ours."""
    teams = []
    for k, score in enumerate(scores):
        num = f"{season}-{k:04d}"
        ours = num in (HIGH, LOW) and season == 19
        teams.append(TeamRow(num, location="GA" if k % 4 == 0 or ours else "TX", ccs_score=score,
                             grp=EMS if ours else "", images=3, place_division=k + 1))
    return Sample(season=season, round_key=round_key, division=division, status=FINAL, source=LEGACY,
                  sampled_at=T0, teams=teams)


INTRO = [300.0 - 2 * k for k in range(100)]          # 300 … 102


@pytest.fixture
def analysis():
    store = SnapshotStore("sqlite://")
    yield AnalysisStore(store)
    store.close()


def _history(analysis):
    """CP-17: the State Round scored 1.5× Round 2 in the same order, and the last 10 teams didn't come back."""
    analysis.save(_sample(17, "r2", INTRO))
    analysis.save(_sample(17, "state", [1.5 * s if k < 90 else 0.0 for k, s in enumerate(INTRO)]))


def test_the_model_learns_from_past_seasons(analysis):
    _history(analysis)
    m = model(analysis, MS, 19)
    assert m.seasons == [17] and m.pairs == 90 and m.rho == pytest.approx(0.99)
    assert m.ratio == pytest.approx(1.5 * 211 / 201, rel=0.01) and m.played == pytest.approx(0.9)
    assumed = model(analysis, MS, 17)                   # its own season doesn't count
    assert assumed.assumed and assumed.rho == 0.6 and assumed.ratio == 1.0 and assumed.played == 1.0


def test_the_projection_after_the_introductory_round(analysis):
    _history(analysis)
    r = round_report(analysis, analysis.save(_sample(19, "r2", INTRO)), "GA", timeline=False)
    a = r.advance
    assert a.stage == "projection" and a.n == 100 and a.line_rank == 60
    by = {p.team.team_number: p for p in a.projections}
    high, low = by[HIGH], by[LOW]
    assert high.intro == 260 and low.intro == 140
    assert high.semis.median < high.expected and high.semis.chance > 0.8
    assert low.semis.median > low.expected and low.semis.chance < 0.2
    assert high.semis.lo <= high.semis.median <= high.semis.hi
    assert high.award and high.award.median > high.semis.median      # top 3 in GA is the harder line
    n = r.narrative["advance"]
    assert n[0].startswith("Under the CP-18 Rules Book, the top 60% of Middle School teams advance")
    assert n[1].startswith("The projection learns from CP-17 (90 teams in both rounds)")
    assert any(s.startswith(f"{HIGH}, 260 points. The Semifinals: ") and "A top-3 GA award: about" in s
               for s in r.narrative["advance_teams"])
    assert any(s.startswith("State Round points needed for the Semifinals (projected):") for s in r.narrative["summary"])
    chart = advance_chart(r)
    assert "data-projection" in chart and 'class="need s1"' in chart and 'class="need s3"' in chart
    assert "Needed for a top-3 GA award" in advance_legend(r)


def test_without_history_the_projection_says_what_it_assumes(analysis):
    r = round_report(analysis, analysis.save(_sample(19, "r2", INTRO)), "GA", timeline=False)
    assert r.advance.model.assumed
    assert any(s.startswith("No past season in the data has both") for s in r.narrative["advance"])


def test_the_line_with_the_state_round_in(analysis):
    analysis.save(_sample(19, "r2", INTRO))
    r = round_report(analysis, analysis.save(_sample(19, "state", [100.0] * 100)), "GA", timeline=False)
    a = r.advance
    assert a.stage == "state" and a.n == 100 and a.line_rank == 60 and a.cut == 282   # 60th: 182 + 100
    assert a.award_cut == 384                          # GA: 19-0000 400, 19-0004 392, 19-0008 384
    by = {s.team.team_number: s for s in a.standings}
    assert by[HIGH].total == 360 and by[HIGH].margin == 360 - 282 and by[LOW].margin == 240 - 282
    assert by[HIGH].state_place is not None
    n = r.narrative["advance_teams"]
    assert any(s.startswith(f"{LOW}: 240 combined (140 + 100), 42 points below the line") for s in n)
    assert any(s.startswith("Semifinal line 282 combined points:") for s in r.narrative["summary"])


def test_other_divisions_and_old_seasons_are_left_out(analysis):
    old = round_report(analysis, analysis.save(_sample(14, "r2", INTRO)), "GA", timeline=False)
    open_ = round_report(analysis, analysis.save(_sample(19, "r2", INTRO, division="Open")), "GA", timeline=False)
    assert old.advance is None and open_.advance is None


def test_the_national_finals_line_after_the_semifinal(analysis):
    r = round_report(analysis, analysis.save(_sample(19, "sf", INTRO)), "GA", timeline=False)
    a = r.advance
    assert a.stage == "semifinal" and a.line_rank == 3 and a.cut == 296
    assert {s.team.team_number: s.margin for s in a.standings} == {HIGH: 260 - 296, LOW: 140 - 296}
    assert r.narrative["advance"][0].endswith("the third-highest score was 296.")
