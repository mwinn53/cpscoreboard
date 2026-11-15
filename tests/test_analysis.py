"""Analysis tab: coach role, round samples, legacy import, sampler and round report."""

import asyncio
import gzip
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from app.analysis import describe, percentile, round_report
from app.analysis_legacy import TOTAL, group_of, import_files, parse_name
from app.analysis_sampler import AnalysisSampler
from app.analysis_store import (DISTRICT, EMS, FINAL, LEGACY, PRELIMINARY, AnalysisStore, ImageRow, Sample, TeamRow,
                                parse_image_name, round_identity)
from app.board_config import BoardConfig
from app.scraper import parse_scores
from app.store import SnapshotStore
from test_auth import device_id, make_admin, register, site  # noqa: F401 (fixture)

FIX = Path(__file__).parent / "fixtures"
T0 = datetime(2026, 11, 15, 12, tzinfo=UTC)


# --- names and identity ---

def test_image_names_and_round_identity():
    assert parse_image_name("Debian12_cp19_intro_r2_hsms") == ("Debian12", 19, "r2")
    assert parse_image_name("Server2022_cp19_r2_hs") == ("Server2022", 19, "r2")
    assert parse_image_name("Win10_cpxii_sf_gsms") == ("Windows10", 12, "sf")
    assert parse_image_name("Windows8_1_cpxi_r2_hsms") == ("Windows8_1", 11, "r2")
    assert parse_image_name("Server2016_cpxi_state_gsms") == ("Server2016", 11, "state")
    assert parse_image_name("Odd") == ("Odd", None, None)
    assert round_identity(["Debian12_cp19_intro_r2_hsms", "Server2022_cp19_r2_hs"], []) == (19, "r2")
    assert round_identity([], ["19-0001", "19-0002"]) == (19, None)


# --- storage ---

def _sample(status=PRELIMINARY, score=100.0, label=""):
    return Sample(season=19, round_key="r2", division="Middle School", status=status, source=LEGACY,
                  sampled_at=T0, label=label,
                  teams=[TeamRow("19-0001", location="GA", ccs_score=score, grp=EMS, place_division=1,
                                 place_state_division=1),
                         TeamRow("19-0002", location="TX", ccs_score=50.0, place_division=2, place_state_division=1)],
                  images=[ImageRow("19-0001", "Windows11", found=10, remaining=5, score=60.0),
                          ImageRow("19-0002", "Windows11", found=5, remaining=10, score=30.0)],
                  timeline=[("19-0001", "Windows11", T0, 60.0)])


def test_save_replaces_and_keeps_a_renamed_label():
    store = SnapshotStore("sqlite://")
    a = AnalysisStore(store)
    info = a.save(_sample())
    assert info.title == "CP-19 Round 2" and info.revision == 1 and info.images == ("Windows11",)
    a.update_round(info.id, label="State Qualifier", notes="Practice Linux")
    again = a.save(_sample(score=120.0))
    assert again.id == info.id and again.revision == 2 and again.label == "State Qualifier"
    assert {t.team_number: t.score for t in a.teams(info.id)}["19-0001"] == 120.0
    assert len(a.images(info.id)) == 2 and len(a.timeline(info.id)) == 1
    final = a.save(_sample(status=FINAL))
    assert final.id != info.id and [r.status for r in a.rounds("Middle School")] == [FINAL, PRELIMINARY]
    a.delete_round(info.id)
    assert a.get(info.id) is None and a.teams(info.id) == []
    store.close()


# --- legacy files ---

SCORES = """,,*Warn,Adjust,CiscoScore,CurrentScore,Division,OverallPlace,PlayTime,ScoredImages,\
Server2019_cpxiv_r1_hsms-Found,Server2019_cpxiv_r1_hsms-Penalties,Server2019_cpxiv_r1_hsms-Remaining,\
Server2019_cpxiv_r1_hsms-Score,Server2019_cpxiv_r1_hsms-Time,State,StatePlace,TeamName,TeamNumber,Tier,TotalScore
1,1,,0.00,20.5,180.0,Middle School,1.0,05:39:59,1,20,0,5,80, 5:38,GA,1.0,Google it,14-0071,Middle School,200.5
2,2,,0.00,10.0,150.0,Middle School,2.0,05:00:00,1,15,0,10,60, 4:00,GA,2.0,GTMS,14-0023,Middle School,160.0
3,3,,0.00,0.0,90.0,Middle School,3.0,04:00:00,1,9,1,16,36, 3:00,TX,1.0,,14-1111,Middle School,90.0
4,4,shifted,row,that,does,not,parse,,,,,,,,,,,,,
"""
TIMES = """,Unnamed: 0,Time,Server2019_cpxiv_r1_hsms,Windows10_cpxiv_r1_hsms,Team
0,0,1900-10-22 13:20:00,5,10,14-0071
1,1,1900-10-22 13:25:00,15,14-0023,
"""


def test_legacy_names_groups_and_files():
    p = parse_name("CP-XIV Semi-Final Round Middle School Division_scores_prelim.csv")
    assert (p.season, p.label, p.division, p.kind, p.status) == (14, "Semi-Final Round", "Middle School", "scores",
                                                                 PRELIMINARY)
    assert parse_name("CP-XI State Round Middle School Division.csv").label == "State Round"
    assert parse_name("output.csv") is None
    assert (group_of("GTMS"), group_of("RMS"), group_of("Google it"), group_of("")) == (DISTRICT, DISTRICT, EMS, "")

    r = import_files([("CP-XIV Round 1 Middle School Division_scores_final.csv", SCORES.encode()),
                      ("CP-XIV Round 1 Middle School Division_times_final.csv", TIMES.encode()),
                      ("CP-XIV State Round Middle School Division_scores_final.csv", SCORES.encode()),
                      ("notes.csv", b"x")])
    assert len(r.samples) == 1
    s = r.samples[0]
    assert (s.season, s.round_key, s.status, s.label) == (14, "r1", FINAL, "Round 1")
    assert [t.team_number for t in s.teams] == ["14-0071", "14-0023", "14-1111"]
    ems = s.teams[0]
    assert (ems.grp, ems.challenge_1, ems.total, ems.play_time, ems.score) == (EMS, 20.5, 200.5, 5 * 3600 + 39 * 60 + 59,
                                                                               200.5)
    assert s.images[0].duration == 5 * 3600 + 38 * 60 and s.images[0].image == "Server2019"
    assert ("14-0071", "Server2019", datetime(2021, 10, 22, 13, 20, tzinfo=UTC), 5.0) in s.timeline
    assert ("14-0023", TOTAL, datetime(2021, 10, 22, 13, 25, tzinfo=UTC), 15.0) in s.timeline  # shifted row: total
    messages = {f.filename: f.message for f in r.files}
    assert "images are from round 'r1'" in messages["CP-XIV State Round Middle School Division_scores_final.csv"]
    assert messages["notes.csv"].startswith("skipped")


# --- statistics ---

def test_describe_and_percentile():
    d = describe([1, 2, 3, 4, 5, None])
    assert (d.n, d.median, d.q1, d.q3, d.min, d.max) == (5, 3, 2, 4, 1, 5)
    assert describe([]).n == 0 and describe([7]).median == 7
    assert percentile(5, [1, 2, 3, 4, 5]) == 100 and percentile(1, [1, 2, 3, 4, 5]) == 0
    assert percentile(3, [3, 3, 3]) == 50


def test_round_report_from_a_sample():
    store = SnapshotStore("sqlite://")
    a = AnalysisStore(store)
    info = a.save(import_files([("CP-XIV Round 1 Middle School Division_scores_final.csv", SCORES.encode())]).samples[0])
    r = round_report(a, info, "GA")
    assert r.counts == {"national": 3, "state": 2, "district": 2, "ems": 1}
    assert r.images[0].name == "Server2019" and r.images[0].total_items == 25
    assert abs(r.ems[0].completion["Server2019"] - 0.8) < 1e-9 and r.ems[0].percentile == 100
    assert r.state_table[1][1] == 40.5 and r.has_challenge
    assert any("outscored 100% of the division" in f for f in r.findings)
    store.close()


# --- sampler ---

BOARD = gzip.decompress((FIX / "scores_s19_2026-11-13.json.gz").read_bytes())
IMAGES = (FIX / "detail" / "images_s19_2026-11-14.json").read_bytes()
CHART = (FIX / "detail" / "image_chart_s19_2026-11-14.json").read_bytes()


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now


def _sampler(watch=()):
    store = SnapshotStore("sqlite://")
    board = BoardConfig(store)
    board.seed(list(watch), "", "", "", "", "Watched", "EMS")
    teams = parse_scores(BOARD)
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/image/scores.php"):
            return httpx.Response(200, content=IMAGES)
        if request.url.path.endswith("/image/chart.php"):
            return httpx.Response(200, content=CHART)
        team = request.url.params["team"]
        return httpx.Response(200, json={"data": [{"team_number": team, "score_1": "12.5", "total": "200.00"}]})

    clock = Clock()
    s = AnalysisSampler(AnalysisStore(store), board, httpx.AsyncClient(transport=httpx.MockTransport(handler)),
                        lambda: teams, lambda: "https://sb.example.org/api/team/scores.php", clock=clock)
    return s, store, teams, calls, clock


def test_sampler_waits_for_quiet_then_samples_each_division_once():
    s, store, teams, calls, clock = _sampler()
    assert s.divisions() == ["Middle School"] and s.quiet_hours() == 24
    s.note_board(teams)
    assert s.last_score_change() == T0 and s.due(teams) == []
    clock.now = T0 + timedelta(hours=23)
    s.note_board(teams)  # nothing changed
    assert s.due(teams) == []
    clock.now = T0 + timedelta(hours=25)
    assert s.due(teams) == ["Middle School"]
    ms = [t for t in teams if t.division == "Middle School"][:3]
    s.full_board = lambda: ms
    info = asyncio.run(s.sample("Middle School"))
    assert (info.season, info.round_key, info.team_count) == (19, "r2", 3) and len(calls) == 9
    assert s.due(teams) == []  # sampled after the last change
    rows = s.store.teams(info.id)
    assert rows[0].challenge_1 == 12.5 and rows[0].total == 200.0
    assert len(s.store.images(info.id)) == 9 and len(s.store.timeline(info.id)) > 9
    store.close()


def test_sampler_marks_our_teams():
    s, store, teams, calls, clock = _sampler()
    ms = [t for t in teams if t.division == "Middle School"][:2]
    s.board.add_watch(ms[0].team_number)
    s.full_board = lambda: ms
    info = asyncio.run(s.sample("Middle School"))
    groups = {t.team_number: (t.grp, t.name) for t in s.store.teams(info.id)}
    assert groups[ms[0].team_number] == (EMS, "EMS") and groups[ms[1].team_number] == ("", "")
    store.close()


# --- coach role and pages ---

def test_coaches_see_the_analysis_tab(site):  # noqa: F811
    admin = make_admin(site)
    coach = site()
    register(coach, site.mailer, "coach@example.com")
    did = device_id(admin, "coach@example.com")
    admin.post(f"/admin/devices/{did}/approve")
    assert coach.get("/analysis").status_code == 403
    assert 'href="/analysis"' not in coach.get("/").text
    assert admin.post(f"/admin/devices/{did}/make-coach").status_code == 303
    assert "coach</span>" in admin.get("/admin").text
    assert coach.get("/analysis").status_code == 200 and 'href="/analysis"' in coach.get("/").text
    assert coach.post("/analysis/settings", data={"divisions": ["Open"]}).status_code == 403  # admin only
    admin.post(f"/admin/devices/{did}/remove-coach")
    assert coach.get("/analysis").status_code == 403
    assert admin.get("/analysis").status_code == 200  # admins are coaches


def test_import_and_round_page(site):  # noqa: F811
    admin = make_admin(site)
    files = [("files", ("CP-XIV Round 1 Middle School Division_scores_final.csv", SCORES.encode(), "text/csv")),
             ("files", ("CP-XIV Round 1 Middle School Division_times_final.csv", TIMES.encode(), "text/csv"))]
    r = admin.post("/analysis/import", files=files)
    assert r.status_code == 200 and "1 round sample imported" in r.text
    page = admin.get("/analysis?division=Middle+School").text
    assert "CP-14 Round 1" in page
    rid = admin.app.state.analysis.rounds("Middle School")[0].id
    report = admin.get(f"/analysis/rounds/{rid}").text
    assert "Findings" in report and "14-0071" in report and "Server2019" in report
    assert admin.post(f"/analysis/rounds/{rid}", data={"label": "R1", "notes": "Good Windows work",
                                                       "status": "final"}).status_code == 303
    assert "Good Windows work" in admin.get(f"/analysis/rounds/{rid}").text
    assert admin.post(f"/analysis/rounds/{rid}/delete").status_code == 303
    assert admin.get(f"/analysis/rounds/{rid}").status_code == 404
