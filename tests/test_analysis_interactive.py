"""Interactive charts (#65): team tags, legend toggles, zoomed re-renders and reading a report for another state."""

import re

import pytest
from test_analysis import _synthetic
from test_auth import make_admin, site  # noqa: F401 (fixture)

from app.analysis import round_report
from app.analysis_charts import (percentile_lines, progress_chart, progress_legend, round_charts, team_legend,
                                 zoomed_chart)
from app.analysis_store import AnalysisStore
from app.store import SnapshotStore


@pytest.fixture
def report():
    store = SnapshotStore("sqlite://")
    a = AnalysisStore(store)
    yield round_report(a, a.save(_synthetic()), "GA")
    store.close()


def _xs(chart: str) -> list[str]:
    return re.findall(r'<text class="tick" x="[\d.]+" y="[\d.]+" text-anchor="middle">([^<]+)</text>', chart)


def test_team_marks_and_legend_toggles(report):
    charts = round_charts(report)
    assert 'data-team="19-0001"' in charts["strips"] and 'data-team="19-0007"' in charts["heatmap"]
    assert 'class="series s2" data-team="19-0001"' in charts["progress"]
    legend = progress_legend(report)
    assert 'data-toggle=".median-line"' in legend and 'data-toggle=".series.s2, .end.s2, .end-label.s2"' in legend
    assert 'data-group="other"' in team_legend("GA") and 'aria-pressed="true"' in team_legend("GA")
    lines = percentile_lines(["R1", "R2"], [("19-0001", [40.0, 60.0])], label="x")
    assert 'class="label-toggle" data-series="s1" role="button" tabindex="0"' in lines


def test_zoomed_charts_are_drawn_for_the_range(report):
    full = round_charts(report)
    assert 'data-zoom="progress"' in full["progress"] and "data-zoomed" not in full["progress"]
    assert 'data-zoom="score_hist" data-x="' in full["score_hist"] and 'data-zoom="time_hist"' in full["time_hist"]
    z = progress_chart(report, window=(60, 150))
    assert "data-zoomed" in z and 'data-x="60,150,' in z
    assert _xs(z) == ["1 h", "1:15", "1:30", "1:45", "2 h", "2:15", "2:30"]
    hist = zoomed_chart(report, "score_hist", 100, 150)
    assert "data-zoomed" in hist and "(zoomed)" in hist
    counts = [int(n) for n in re.findall(r": (\d+) teams", hist)]
    assert sum(counts) == sum(1 for t in report.teams if 100 <= t.score <= 150)
    assert zoomed_chart(report, "heatmap", 0, 10) == "" and zoomed_chart(report, "progress", 50, 50) == ""


def test_the_report_page_for_another_state_and_a_zoomed_chart(site):  # noqa: F811
    admin = make_admin(site)
    info = admin.app.state.analysis.save(_synthetic())
    page = admin.get(f"/analysis/reports/{info.id}").text
    assert f'data-report="{info.id}" data-state="GA"' in page and 'id="team-list"' in page
    assert '<tr data-team="19-0001">' in page and "Read for GA:" not in page
    tx = admin.get(f"/analysis/reports/{info.id}?state=tx").text
    assert 'data-state="TX"' in tx and "Read for TX:" in tx and "<h2>TX teams</h2>" in tx
    assert 'data-state="GA"' in admin.get(f"/analysis/reports/{info.id}?state=ZZ").text   # no teams there
    z = admin.get(f"/analysis/reports/{info.id}/charts/progress?lo=60&hi=180")
    assert z.status_code == 200 and z.text.startswith('<div class="chart-wrap"') and "data-zoomed" in z.text
    assert admin.get(f"/analysis/reports/{info.id}/charts/heatmap?lo=0&hi=10").status_code == 404
