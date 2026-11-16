"""Analysis tab: coach role, data sets, legacy import, collector, reports, charts and comparisons."""

import asyncio
import dataclasses
import gzip
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import unquote

import httpx

from app.analysis import cached_report, describe, percentile, round_report, team_curves, value_at
from app.analysis_charts import round_charts
from app.analysis_collector import AnalysisCollector
from app.analysis_compare import history_view, pair_view, pick, season_view
from app.analysis_legacy import TOTAL, group_of, import_files, parse_name
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
    assert any("outscoring 100% of the division" in f for f in r.narrative["summary"])
    store.close()


# --- a bigger synthetic round: narrative, charts, progress ---

def _synthetic(season=19, round_key="r1", status=FINAL, n=40, shift=0.0, ours=(1, 7)):
    teams, images, timeline = [], [], []
    for k in range(n):
        num = f"{season}-{k:04d}"
        grp = EMS if k in ours else DISTRICT if k in (4, 10) else ""
        score = 200 - k * 4 + shift
        two = k < n - 3
        teams.append(TeamRow(num, location=("GA", "TX", "CA", "VA")[k % 4], ccs_score=score, grp=grp,
                             name="Ours" if grp == EMS else "", images=2 if two else 1,
                             play_time=5 * 3600 + k * 60, place_division=k + 1))
        for img, total in (("Windows10", 20), ("Server2019", 25)):
            if img == "Server2019" and not two:
                continue
            found = max(0, total - k // 2)
            images.append(ImageRow(num, img, found=found, remaining=total - found, score=score / 2))
            for h in range(7):
                timeline.append((num, img, T0 + timedelta(minutes=k + h * 60), score / 2 * h / 6))
    for state in ("GA", "TX", "CA", "VA"):
        for place, t in enumerate([t for t in teams if t.location == state], start=1):
            t.place_state_division = place
    return Sample(season=season, round_key=round_key, division="Middle School", status=status, source=LEGACY,
                  sampled_at=T0, teams=teams, images=images, timeline=timeline)


def test_progress_curves_hold_and_sum_images():
    curves = team_curves([("a", "Win", T0, 5.0), ("a", "Srv", T0 + timedelta(minutes=10), 3.0),
                          ("a", "Win", T0 + timedelta(minutes=20), 9.0),
                          ("b", TOTAL, T0, 4.0), ("b", TOTAL, T0 + timedelta(minutes=30), 8.0)])
    assert curves["a"] == [(0.0, 5.0), (10.0, 8.0), (20.0, 12.0)] and curves["b"][-1] == (30.0, 8.0)
    assert value_at(curves["a"], 15) == 8.0 and value_at(curves["a"], 500) == 12.0


def test_narrative_and_charts_for_a_round():
    store = SnapshotStore("sqlite://")
    a = AnalysisStore(store)
    info = a.save(_synthetic())
    r = round_report(a, info, "GA")
    assert r.density.rank is not None and len(r.density.states) == 4 and r.attempts.fewer == 3
    assert r.progress and r.progress.teams == 40 and r.ems[0].hourly[6] > 90
    n = r.narrative
    assert n["overview"][0].startswith("40 Middle School teams competed in CP-19 Round 1, 10 of them from GA")
    assert any("attempted fewer" in s for s in n["attempts"])
    assert any("ahead of the median throughout" in s for s in n["progress"])
    assert n["summary"][0].startswith("Best result: 19-0001 (Ours)")
    charts = round_charts(r)
    for key in ("state_boxes", "strips", "score_hist", "time_hist", "heatmap", "density", "attempts", "completion",
                "finds:Windows10"):
        assert charts[key].startswith('<div class="chart-wrap" data-tips>') and "data-tip=" in charts[key], key
    assert 'class="dot ours"' in charts["strips"] and 'class="box hl"' in charts["state_boxes"]
    assert "data-points=" in charts["progress"] and "series s2" in charts["progress"]
    assert cached_report(a, info, "GA") is not cached_report(a, info, "TX")
    assert cached_report(a, info, "GA").ems == cached_report(a, info, "GA").ems
    store.close()


def test_season_history_and_pair_comparisons():
    store = SnapshotStore("sqlite://")
    a = AnalysisStore(store)
    r1 = a.save(_synthetic(18, "r1"))
    a.save(_synthetic(18, "r2", n=30))
    a.save(_synthetic(19, "r1", shift=10, ours=(0, 9)))
    pre = a.save(_synthetic(19, "r2", status=PRELIMINARY, ours=(0, 5)))
    final = a.save(_synthetic(19, "r2", ours=(0, 2)))
    assert [x.id for x in pick(a.rounds("Middle School"))][-1] == final.id  # final over preliminary
    season = season_view(a, "Middle School", 19, "GA")
    assert [s.info.label for s in season.summaries] == ["Round 1", "Round 2"]
    assert len(season.teams) == 3 and "percentile by round" in season.chart
    assert any("19-0000" in s and "rose" in s or "held steady" in s or "fell" in s for s in season.narrative)
    hist = history_view(a, "Middle School", "GA")
    assert hist.seasons == [18, 19] and hist.labels == ["Round 1", "Round 2"]
    assert hist.grid[("Round 2", 18)].counts["national"] == 30
    assert any(s.startswith("Round 2: national participation up 33%") for s in hist.narrative)
    pair = pair_view(a, final, pre, "GA")
    assert pair.a.info.id == pre.id and [o.team_number for o, _ in pair.matched] == ["19-0000"]
    cross = pair_view(a, r1, final, "GA")
    assert cross.matched == [] and any("compared as a program" in s for s in cross.narrative)
    store.close()


# --- collector ---

BOARD = gzip.decompress((FIX / "scores_s19_2026-11-13.json.gz").read_bytes())
IMAGES = (FIX / "detail" / "images_s19_2026-11-14.json").read_bytes()
CHART = (FIX / "detail" / "image_chart_s19_2026-11-14.json").read_bytes()


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now


def _collector(watch=(), n=3):
    store = SnapshotStore("sqlite://")
    board = BoardConfig(store)
    board.seed(list(watch), "", "", "", "", "Watched", "EMS")
    teams = [t for t in parse_scores(BOARD) if t.division == "Middle School" and (t.play_time or 0) >= 4 * 3600][:n]
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
    box = {"teams": teams}
    c = AnalysisCollector(AnalysisStore(store), board, httpx.AsyncClient(transport=httpx.MockTransport(handler)),
                          lambda: box["teams"], lambda: "https://sb.example.org/api/team/scores.php", clock=clock)
    return c, store, box, calls, clock


def test_collector_waits_for_play_time_to_stop_then_collects_a_team_at_a_time():
    c, store, box, calls, clock = _collector()
    assert c.divisions() == ["Middle School"] and c.concurrency() == 1
    assert c.plan() == [] and c.status["Middle School"].playing == 3      # just seen: still playing
    clock.now = T0 + timedelta(minutes=59)
    assert c.plan() == []                                                  # idle, but not for an hour yet
    clock.now = T0 + timedelta(minutes=61)
    pending = c.plan()
    st = c.status["Middle School"]
    assert len(pending) == 3 and (st.waiting, st.collected, st.played) == (3, 0, 3) and st.eta_seconds > 0

    async def go():
        assert c.start_fetches(pending) == 1                               # the throttle: one at a time
        await asyncio.gather(*c.tasks)
        c.set_concurrency(5)
        assert c.start_fetches(c.plan()) == 2
        await asyncio.gather(*c.tasks)
    asyncio.run(go())
    assert len(calls) == 9
    st = c.plan() and None or c.status["Middle School"]
    assert st.complete and st.percent == 100 and c.plan() == []
    info = c.store.get(st.round_id)
    assert (info.season, info.round_key, info.team_count, info.source) == (19, "r2", 3, "live")
    rows = {t.team_number: t for t in c.store.teams(info.id)}
    t0 = box["teams"][0]
    assert rows[t0.team_number].challenge_1 == 12.5 and rows[t0.team_number].total == 200.0
    assert len(c.store.images(info.id)) == 9 and len(c.store.timeline(info.id)) > 9

    # places move while others play: refreshed from the board without fetching
    box["teams"] = [dataclasses.replace(t0, place_division=99)] + box["teams"][1:]
    assert c.refresh() == 1 and {t.team_number: t for t in c.store.teams(info.id)}[t0.team_number].place_division == 99
    # a later score change collects the team again
    box["teams"] = [dataclasses.replace(t0, ccs_score=(t0.ccs_score or 0) + 5)] + box["teams"][1:]
    assert [t.team_number for t in c.plan()] == [t0.team_number] and c.status["Middle School"].collected == 2
    c.set_concurrency(0)
    assert c.start_fetches(c.plan()) == 0                                  # paused
    store.close()


def test_collector_waits_longer_for_teams_that_stopped_short_of_4_hours():
    c, store, box, calls, clock = _collector(n=1)
    short = dataclasses.replace(box["teams"][0], play_time=2 * 3600)
    box["teams"] = [short]
    c.plan()
    clock.now = T0 + timedelta(hours=3, minutes=59)
    assert c.plan() == [] and c.status["Middle School"].playing == 1
    clock.now = T0 + timedelta(hours=4, minutes=1)
    assert [t.team_number for t in c.plan()] == [short.team_number]
    store.close()


def test_collect_all_takes_unfinished_teams_once_at_the_same_throttle():
    c, store, box, calls, clock = _collector()
    assert c.plan() == []                                                  # just seen: not finished
    c.collect_all("Middle School")
    pending = c.plan()
    assert len(pending) == 3 and c.status["Middle School"].forced

    async def go():
        assert c.start_fetches(pending) == 1                               # still one at a time
        await asyncio.gather(*c.tasks)
        while c.start_fetches(c.plan()):
            await asyncio.gather(*c.tasks)
    asyncio.run(go())
    assert c.plan() == [] and c.status["Middle School"].complete and not c.forced
    store.close()


def test_collector_takes_the_cisco_scores_from_the_board_feed():
    c, store, box, calls, clock = _collector(n=1)
    t = box["teams"][0]
    t.raw.update({"score_1": "7.00", "score_2": "3.00", "total": "150.00"})
    asyncio.run(c.collect(t))
    assert len(calls) == 2                                                 # no request for the team's own row
    row = c.store.teams(c.store.rounds("Middle School")[0].id)[0]
    assert (row.challenge_1, row.challenge_2, row.cisco, row.total) == (7.0, 3.0, 10.0, 150.0)
    store.close()


def test_collector_marks_our_teams():
    c, store, box, calls, clock = _collector(n=2)
    c.board.add_watch(box["teams"][0].team_number)
    clock.now = T0
    c.plan()
    clock.now = T0 + timedelta(minutes=65)
    for t in c.plan():
        asyncio.run(c.collect(t))
    info = c.store.get(c.plan() and None or c.status["Middle School"].round_id)
    groups = {t.team_number: (t.grp, t.name) for t in c.store.teams(info.id)}
    assert groups[box["teams"][0].team_number] == (EMS, "EMS") and groups[box["teams"][1].team_number] == ("", "")
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
    assert r.status_code == 200 and "1 data set imported" in r.text
    page = admin.get("/analysis?division=Middle+School").text
    assert "CP-14 Round 1" in page and "Reports" in page and "/analysis/seasons/14" in page
    rid = admin.app.state.analysis.rounds("Middle School")[0].id
    report = admin.get(f"/analysis/reports/{rid}").text
    assert "In brief" in report and "14-0071" in report and "Server2019" in report and "chart-wrap" in report
    old = admin.get(f"/analysis/rounds/{rid}", follow_redirects=False)
    assert old.headers["location"] == f"/analysis/reports/{rid}"
    assert "Season over season" in admin.get("/analysis/seasons?division=Middle+School").text
    assert "CP-14" in admin.get("/analysis/seasons/14?division=Middle+School").text
    assert admin.get("/analysis/seasons/9?division=Middle+School").status_code == 404
    assert "Collection is off here" in admin.get("/analysis/partials/collection?division=Middle+School").text
    assert admin.post(f"/analysis/reports/{rid}", data={"label": "R1", "notes": "Good Windows work",
                                                        "status": "final"}).status_code == 303
    assert "Good Windows work" in admin.get(f"/analysis/reports/{rid}").text
    assert admin.post(f"/analysis/reports/{rid}/delete").status_code == 303
    assert admin.get(f"/analysis/reports/{rid}").status_code == 404


def test_compare_page(site):  # noqa: F811
    admin = make_admin(site)
    a = admin.app.state.analysis
    one, two = a.save(_synthetic(19, "r1")), a.save(_synthetic(19, "r2"))
    page = admin.get(f"/analysis/compare?a={two.id}&b={one.id}").text
    assert "CP-19 Round 1</a>" in page and "Side by side" in page and "19-0001" in page
    assert admin.get(f"/analysis/compare?a={one.id}&b={one.id}").status_code == 400


def test_collection_panel_and_throttle(site):  # noqa: F811
    admin = make_admin(site)
    app = admin.app
    c, store, box, calls, clock = _collector()
    c.store, c.board = app.state.analysis, app.state.board
    app.state.collector = c
    clock.now = T0 + timedelta(minutes=30)
    c.observe(box["teams"])
    clock.now = T0 + timedelta(minutes=95)
    c.plan()
    page = admin.get("/analysis/partials/collection?division=Middle+School").text
    assert "0</strong> of 3 teams' data sets complete" in page and "3 waiting" in page
    assert 'type="range"' in admin.get("/analysis?division=Middle+School").text
    r = admin.post("/analysis/throttle", data={"concurrency": "3", "division": "Middle School"},
                   headers={"HX-Request": "true"})
    assert r.status_code == 200 and c.concurrency() == 3 and "teams' data sets complete" in r.text
    assert admin.post("/analysis/throttle", data={"concurrency": "0", "division": "Middle School"}).status_code == 303
    assert "Collection is paused" in admin.get("/analysis/partials/collection?division=Middle+School").text
    home = admin.get("/analysis?division=Middle+School").text
    assert "Collect all Middle School teams now" in home and "including teams still" in home
    r = admin.post("/analysis/collect-all", data={"division": "Middle School"}, headers={"HX-Request": "true"})
    assert r.status_code == 200 and "Collecting all teams now" in r.text and "Middle School" in c.forced
    assert admin.post("/analysis/collect-all", data={"division": "Open"}).status_code == 400
    store.close()


def test_round_setting_overrides_image_names_and_moves_the_data_set(site):  # noqa: F811
    admin = make_admin(site)
    app = admin.app
    c, store, box, calls, clock = _collector(n=2)
    c.store, c.board = app.state.analysis, app.state.board
    app.state.collector = c
    asyncio.run(c.collect(box["teams"][0]))                                 # images say r2
    c.plan()
    first = c.store.get(c.status["Middle School"].round_id)
    assert first.round_key == "r2" and first.label == "Round 2"
    r = admin.post("/analysis/round", data={"round_key": "r1", "division": "Middle School"}, follow_redirects=False)
    assert r.status_code == 303 and "Moved the data set" in unquote(r.headers["location"])
    moved = c.store.get(first.id)
    assert (moved.round_key, moved.label, c.round_key()) == ("r1", "Round 1", "r1")
    asyncio.run(c.collect(box["teams"][1]))                                 # later teams land in Round 1 too
    assert c.store.get(first.id).team_count == 2 and len(c.store.rounds("Middle School")) == 1
    # a report's round can be fixed by hand; a renamed label is kept
    c.store.update_round(first.id, label="Opening round")
    assert admin.post(f"/analysis/reports/{first.id}", data={"label": "Opening round", "round_key": "r3"}).status_code == 303
    assert (c.store.get(first.id).round_key, c.store.get(first.id).label) == ("r3", "Opening round")
    assert "Round being collected" in admin.get("/analysis?division=Middle+School").text
    store.close()


def test_coaches_correct_a_teams_group(site):  # noqa: F811
    admin = make_admin(site)
    a = admin.app.state.analysis
    info = a.save(_synthetic(19, "r1"))
    r = admin.post(f"/analysis/reports/{info.id}/group", data={"team_number": "19-0003", "grp": "ems", "name": "New"},
                   follow_redirects=False)
    assert r.status_code == 303 and "one of our teams" in unquote(r.headers["location"])
    row = {t.team_number: t for t in a.teams(info.id)}["19-0003"]
    assert (row.grp, row.name) == (EMS, "New") and a.get(info.id).revision == 2
    assert "19-0003 (New)" in admin.get(f"/analysis/reports/{info.id}").text   # the cached report is redone
    r = admin.post(f"/analysis/reports/{info.id}/group", data={"team_number": "99-9999", "grp": ""},
                   follow_redirects=False)
    assert "No team 99-9999" in unquote(r.headers["location"])
