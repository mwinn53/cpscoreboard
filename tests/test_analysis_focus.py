"""Where the points went (app/analysis_focus.py): points within reach, strengths and weaknesses, penalties."""

from datetime import UTC, datetime

import pytest

from app.analysis import round_report
from app.analysis_compare import family_strength, season_view
from app.analysis_focus import points_per_item, top_quarter_found
from app.analysis_stats import holm
from app.analysis_store import EMS, FINAL, LEGACY, AnalysisStore, ImageRow, Sample, TeamRow
from app.store import SnapshotStore

T0 = datetime(2026, 11, 15, 12, tzinfo=UTC)
WIN, SRV = "Windows10", "Server2019"
PER = {WIN: 3.0, SRV: 5.0}         # points per item
ITEMS = {WIN: 20, SRV: 10}
OURS = ("19-0005", "19-0009")


def _round(round_key="r1", weak_server=True, our_penalties=2):
    """20 teams, half in GA. Our two teams are mid-field overall but weak on Server; 19-0005 takes penalties."""
    rows = []
    for k in range(20):
        num = f"19-{k:04d}"
        win = 19 - k // 2
        srv = 9 - k // 3
        if weak_server and num in OURS:
            win, srv = 19, 2              # strong on Windows, weak on Server: a mid-field total
        pens = our_penalties if num == "19-0005" else (1 if k == 12 else 0)
        rows.append((num, win, srv, pens))
    teams, images = [], []
    for num, win, srv, pens in rows:
        win_score = win * PER[WIN] - 3 * pens
        srv_score = srv * PER[SRV]
        teams.append(TeamRow(num, location="GA" if int(num[3:]) % 2 == 0 or num in OURS else "TX",
                             ccs_score=win_score + srv_score, grp=EMS if num in OURS else "", images=2,
                             play_time=4 * 3600))
        images.append(ImageRow(num, WIN, found=win, remaining=ITEMS[WIN] - win, penalties=pens, score=win_score))
        images.append(ImageRow(num, SRV, found=srv, remaining=ITEMS[SRV] - srv, penalties=0, score=srv_score))
    ranked = sorted(teams, key=lambda t: -t.score)
    for place, t in enumerate(ranked, start=1):
        t.place_division = place
    for state in ("GA", "TX"):
        for place, t in enumerate([t for t in ranked if t.location == state], start=1):
            t.place_state_division = place
    return Sample(season=19, round_key=round_key, division="Middle School", status=FINAL, source=LEGACY,
                  sampled_at=T0, teams=teams, images=images)


@pytest.fixture
def analysis():
    store = SnapshotStore("sqlite://")
    yield AnalysisStore(store)
    store.close()


def test_points_per_item_and_the_top_quarter():
    rows = [ImageRow(f"t{k}", SRV, found=k, remaining=10 - k, penalties=0, score=5.0 * k) for k in range(1, 11)]
    rows.append(ImageRow("pen", SRV, found=10, remaining=0, penalties=3, score=20.0))   # left out: penalties
    assert points_per_item(rows) == 5.0 and points_per_item(rows, more_than=8) == 5.0
    assert top_quarter_found(rows) == 8.5 and top_quarter_found(rows[:3]) is None


def test_points_within_reach_and_what_it_would_take(analysis):
    r = round_report(analysis, analysis.save(_round()), "GA", timeline=False)
    gaps = {g.result.team.team_number: g for g in r.focus.gaps}
    g = gaps["19-0005"]
    srv = next(s for s in g.sources if s.image == SRV)
    assert srv.per_item == 5.0 and srv.items >= 5 and srv.points == srv.items * 5.0
    win = next(s for s in g.sources if s.image == WIN)
    assert win.items == 0 and win.penalty == pytest.approx(6.0)   # 2 penalties × 3 points
    assert srv.places_state > 0 and srv.places_national >= srv.places_state
    nxt = g.targets[0]
    assert nxt.label.endswith("in GA") and nxt.gap > 0 and nxt.reachable
    assert nxt.plan[0] == (WIN, "no penalties", pytest.approx(6.0))     # penalties first: no new items needed
    assert r.focus.cheapest[0] == SRV
    reach = r.narrative["reach"]
    assert reach[0] == (f"The most points within reach were on {SRV}: both our teams found a median 5 items fewer "
                        "than the field's top quarter there (≈ 25 points).")
    assert any("19-0005" in s and "would have covered it" in s for s in reach)
    assert any(s.startswith(f"Most points within reach: {SRV}") for s in r.narrative["summary"])


def test_strengths_and_weaknesses_against_the_overall_result(analysis):
    r = round_report(analysis, analysis.save(_round()), "GA", timeline=False)
    rel = r.focus.relative
    assert rel.images == [SRV, WIN]
    cells = next(c for res, c in rel.rows if res.team.team_number == "19-0009")
    assert cells[SRV][1] <= -rel.threshold and cells[WIN][1] >= rel.threshold
    flagged = rel.flagged()
    assert {(img, gap < 0) for _, img, gap in flagged} == {(SRV, True), (WIN, False)}
    assert any("weaker on Server2019 (−" in s and "stronger on Windows10 (+" in s for s in r.narrative["relative"])


def test_penalties_against_the_field(analysis):
    r = round_report(analysis, analysis.save(_round()), "GA", timeline=False)
    row = next(x for x in r.focus.penalties if x.image == WIN)
    assert (row.ours_with, row.ours_n, row.field_with, row.field_n) == (1, 2, 1, 18)
    assert row.higher and 0 < row.p <= 1 and row.ours_lost == pytest.approx(6.0)
    assert next(x for x in r.focus.penalties if x.image == SRV).p is None   # nobody penalised there
    pen = r.narrative["penalties"]
    assert pen[0] == "Penalties cost our teams about 6 points together."
    assert any(s.startswith("On Windows10, 1 of our 2 teams took a penalty") for s in pen)
    clean = round_report(analysis, analysis.save(_round("r2", our_penalties=0)), "GA", timeline=False)
    assert clean.narrative["penalties"][0] == "None of our teams took a penalty."


def test_holm_adjusts_in_the_order_given():
    assert holm([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])
    assert holm([0.5, 0.9]) == pytest.approx([1.0, 1.0]) and holm([]) == []


def test_a_family_that_is_weak_across_rounds(analysis):
    for key in ("r1", "r2", "r3"):
        analysis.save(_round(key))
    view = season_view(analysis, "Middle School", 19, "GA")
    by = {f.family: f for f in view.strength}
    server, windows = by["Windows Server"], by["Windows"]
    assert server.n == 6 and server.median < -20 and server.below == 6 and server.rounds_below == 3
    assert server.test is not None and server.p_holm >= server.test.p and windows.median > 0
    assert view.strength[0].family == "Windows Server"                     # weakest first
    assert any(s.startswith("Relative to our overall results, Windows Server was our weakest image family: "
                            "below in 3 of 3 rounds") for s in view.narrative)
    assert family_strength([]) == []
