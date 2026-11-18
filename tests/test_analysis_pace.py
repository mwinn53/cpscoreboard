"""Pace against the top quarter (app/analysis_pace.py): where in the round our teams fall behind."""

from datetime import UTC, datetime, timedelta

import pytest

from app.analysis import round_report
from app.analysis_charts import progress_chart, progress_legend
from app.analysis_legacy import TOTAL
from app.analysis_pace import image_marks
from app.analysis_store import EMS, FINAL, LEGACY, AnalysisStore, ImageRow, Sample, TeamRow
from app.store import SnapshotStore

T0 = datetime(2026, 11, 15, 12, tzinfo=UTC)
IMAGES = ("Windows10", "Server2019")
SLOW_START = "19-0010"     # scores nothing in the first hour, then catches up to its final score
STEADY = "19-0012"         # the same pace as everyone else, just lower


def _round(slow=True):
    """20 teams, 4 hours, each scoring evenly on two images; our slow starter idles for the first hour."""
    teams, images, timeline = [], [], []
    for k in range(20):
        num = f"19-{k:04d}"
        final = 200.0 - 8 * k
        ours = num in (SLOW_START, STEADY)
        teams.append(TeamRow(num, location="GA", ccs_score=final, grp=EMS if ours else "", images=2,
                             play_time=4 * 3600, place_division=k + 1, place_state_division=k + 1))
        start = T0 + timedelta(minutes=k)
        for img in IMAGES:
            images.append(ImageRow(num, img, found=10, remaining=0, score=final / 2))
            for m in range(0, 241, 10):
                if slow and num == SLOW_START:
                    frac = 0.0 if m <= 60 else (m - 60) / 180
                else:
                    frac = m / 240
                timeline.append((num, img, start + timedelta(minutes=m), final / 2 * frac))
    return Sample(season=19, round_key="r1", division="Middle School", status=FINAL, source=LEGACY,
                  sampled_at=T0, teams=teams, images=images, timeline=timeline)


@pytest.fixture
def analysis():
    store = SnapshotStore("sqlite://")
    yield AnalysisStore(store)
    store.close()


def test_the_top_quarter_and_where_the_gap_opened(analysis):
    r = round_report(analysis, analysis.save(_round()), "GA")
    pc = r.pace
    assert pc.top_n == 5 and pc.cut == pytest.approx(162.0)        # q3 of 48 … 200
    top = pc.hourly_median()
    assert top[0] == 0 and top[-1] == pytest.approx(184.0)          # the top five's median final score
    slow = next(t for t in pc.teams if t.team == SLOW_START)
    assert slow.gap[1] == pytest.approx(46.0) and slow.final_gap == pytest.approx(64.0)
    assert slow.worst_hour == 1 and slow.first_hour_share == pytest.approx(46 / 64)
    steady = next(t for t in pc.teams if t.team == STEADY)
    assert steady.worst_hour == 1 and steady.first_hour_share == pytest.approx(0.25)   # even growth: hour 1
    img = next(i for i in pc.images if i.image == "Server2019")
    assert img.top_first == 10 and img.ours[SLOW_START] == (70, 150) and img.ours[STEADY] == (10, 120)
    pace = r.narrative["pace"]
    assert pace[0] == ("The top quarter here is the 5 teams with a 5-minute history that finished on 162 points "
                       "or more.")
    assert any(s.startswith(SLOW_START) and "(72%) opened in the first hour" in s for s in pace)
    assert f"For {SLOW_START}, the opening checklist is worth practicing: that's where the ground was lost." in pace
    assert any(s.startswith(STEADY) and "the gap grew most in hour 1" in s for s in pace)
    assert any(s.startswith("On Server2019, our teams' first points came after a median 40 min, against 10 min")
               for s in pace)
    assert any(s.startswith("Most ground lost to the top quarter: hour 1") for s in r.narrative["summary"])
    chart = progress_chart(r)
    assert 'class="band top"' in chart and 'class="top-line"' in chart and "top quarter 184" in chart
    assert "Top quarter median" in progress_legend(r)


def test_keeping_pace(analysis):
    r = round_report(analysis, analysis.save(_round(slow=False)), "GA")
    assert any("started scoring within 15 minutes of the top quarter" in s for s in r.narrative["pace"])
    assert not any("opening checklist" in s for s in r.narrative["summary"])


def test_no_pace_without_a_history(analysis):
    r = round_report(analysis, analysis.save(_round()), "GA", timeline=False)
    assert r.pace is None and r.narrative["pace"] == []


def test_image_marks_skip_totals_and_scoreless_images():
    rows = [("a", "Win", T0, 0.0), ("a", "Win", T0 + timedelta(minutes=10), 4.0),
            ("a", "Win", T0 + timedelta(minutes=30), 10.0), ("a", "Srv", T0 + timedelta(minutes=5), 0.0),
            ("b", TOTAL, T0, 5.0)]
    assert image_marks(rows) == {"a": {"Win": (10.0, 30.0)}}
