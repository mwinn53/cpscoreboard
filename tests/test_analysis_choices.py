"""Coach-chosen comparisons (#67): teams to follow, another state and the top N, saved per division."""

import re

from test_analysis import _synthetic
from test_auth import make_admin, site  # noqa: F401 (fixture)

from app.analysis import round_report
from app.analysis_choices import Choices, comparison, load, parse_teams, save
from app.analysis_store import AnalysisStore
from app.store import SnapshotStore


class _Board:
    def __init__(self):
        self.values = {}

    def get_value(self, key):
        return self.values.get(key, "")

    def set_value(self, key, value):
        self.values[key] = value


def test_parse_load_and_save():
    assert parse_teams("19-0002, 19-0003\n19-0002 junk 1234 19-12345") == ["19-0002", "19-0003"]
    assert len(parse_teams(" ".join(f"19-{k:04d}" for k in range(60)))) == 40
    board = _Board()
    assert load(board, "Middle School") == Choices()
    save(board, "Middle School", Choices(["19-0002"], "TX", 10))
    assert load(board, "Middle School") == Choices(["19-0002"], "TX", 10)
    assert load(board, "High School") == Choices()
    board.values["compare:Middle School"] = "{not json"
    assert load(board, "Middle School") == Choices()


def test_comparison_groups():
    store = SnapshotStore("sqlite://")
    a = AnalysisStore(store)
    r = round_report(a, a.save(_synthetic()), "GA")
    cmp = comparison(r, Choices(["19-0002", "19-0003", "19-9999"], "TX", 10))
    assert [g.key for g in cmp.groups] == ["national", "state", "other", "top", "follow", "ours"]
    assert [g.label for g in cmp.groups][2:4] == ["TX", "Top 10 nationally"]
    assert cmp.groups[3].score.n == 10 and cmp.groups[0].test is None and cmp.groups[2].test is not None
    assert [f.team.team_number for f in cmp.followed] == ["19-0002", "19-0003"]
    assert cmp.followed[0].state_place == 1 and cmp.followed[0].team.location == "CA"
    assert cmp.missing == ["19-9999"] and cmp.other_state == "TX"
    # the state read for isn't also "another state"; top 0 is off
    cmp = comparison(r, Choices([], "GA", 0))
    assert [g.key for g in cmp.groups] == ["national", "state", "ours"] and cmp.other_state == ""
    store.close()


def test_choices_on_the_report_and_season_pages(site):  # noqa: F811
    admin = make_admin(site)
    analysis = admin.app.state.analysis
    info = analysis.save(_synthetic())
    analysis.save(_synthetic(round_key="r2", shift=10))
    page = admin.get(f"/analysis/reports/{info.id}").text
    assert 'id="compare"' in page and "Choose comparisons for Middle School" in page and 'data-follow=""' in page
    r = admin.post("/analysis/choices", data={"division": "Middle School", "teams": "19-0002 19-0003 19-9999",
                                              "state": "tx", "top": "10", "back": f"/analysis/reports/{info.id}"},
                   follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith(f"/analysis/reports/{info.id}?notice=")
    page = admin.get(f"/analysis/reports/{info.id}").text
    assert 'data-follow="19-0002 19-0003 19-9999"' in page and "<h3>Teams we follow</h3>" in page
    assert "Not in this data set: 19-9999." in page and "Top 10 nationally" in page
    assert "Scores by comparison group" in page
    assert re.search(r'<tr data-team="19-0002"><td>19-0002', page)
    season = admin.get("/analysis/seasons/19?division=Middle%20School").text
    assert "the teams we follow, percentile by round" in season and "TX median team" in season
    assert "Choose comparisons for Middle School" in season
    # a bad state, and a back link off the site, are refused or replaced
    assert admin.post("/analysis/choices", data={"division": "Middle School", "state": "Texas"}).status_code == 400
    r = admin.post("/analysis/choices", data={"division": "Middle School", "back": "https://evil.example/"},
                   follow_redirects=False)
    assert r.headers["location"].startswith("/analysis?division=Middle%20School")
