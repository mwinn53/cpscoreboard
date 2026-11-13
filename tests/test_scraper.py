from collections import Counter

import pytest

from app.scraper import (ScoreboardFormatError, parse_alias_file, parse_hms, parse_scores,
                         parse_team_file)
from conftest import S17, S19, load


def test_parse_season17_fixture():
    teams = parse_scores(load(S17))
    assert len(teams) == 3432
    first = teams[0]
    assert first.team_number == "17-1141"
    assert (first.location, first.division) == ("CA", "Open")
    assert first.play_time == 3 * 3600 + 48 * 60 + 50
    assert first.ccs_score == 298 and first.total == 327 and first.adjustment == 0
    assert first.score == 327
    assert (first.place_overall, first.place_division, first.place_state, first.place_state_division) == (1, 1, 1, 1)

    second = teams[1]  # 17-0224, OR
    assert (second.place_overall, second.place_division, second.place_state) == (2, 2, 1)

    penalized = teams[-1]
    assert penalized.code == "MT" and penalized.adjustment == -290 and penalized.total == -180


def test_parse_season19_fixture_without_totals():
    teams = parse_scores(load(S19))
    assert len(teams) == 1478
    assert all(t.total is None and t.adjustment is None for t in teams)
    assert {t.tier for t in teams} == {"High School", "Middle School"}
    assert teams[0].score == teams[0].ccs_score


@pytest.mark.parametrize("fixture", [S17, S19])
def test_places_follow_api_order(fixture):
    teams = parse_scores(load(fixture))
    seen = Counter()
    for i, t in enumerate(teams, 1):
        assert t.place_overall == i
        seen["d", t.division] += 1
        seen["s", t.location] += 1
        seen["sd", t.location, t.division] += 1
        assert t.place_division == seen["d", t.division]
        assert t.place_state == seen["s", t.location]
        assert t.place_state_division == seen["sd", t.location, t.division]


def test_tolerates_missing_and_blank_fields():
    teams = parse_scores({"data": [
        {"team_number": "19-0001", "ccs_score": "", "play_time": "", "images": None},
        {"team_number": ""},  # skipped
        "junk",               # skipped
        {"team_number": "19-0002", "ccs_score": "12", "location": "VA"},
    ]})
    assert [t.team_number for t in teams] == ["19-0001", "19-0002"]
    assert teams[0].ccs_score is None and teams[0].play_time is None and teams[0].score == 0
    assert teams[1].place_overall == 2 and teams[1].place_state == 1


def test_empty_board_is_valid():
    assert parse_scores(b'{"data": []}') == []


@pytest.mark.parametrize("payload", [b"<!DOCTYPE html><html></html>", b'{"rows": []}', b"[]", b"\xff\xfe"])
def test_rejects_non_scoreboard_payloads(payload):
    with pytest.raises(ScoreboardFormatError):
        parse_scores(payload)


@pytest.mark.parametrize("value,expected", [
    ("03:48:50", 13730), ("00:00:00", 0), ("123:00:01", 442801),
    ("", None), (None, None), ("05:00", None), ("aa:bb:cc", None),
])
def test_parse_hms(value, expected):
    assert parse_hms(value) == expected


def test_parse_legacy_alias_file():
    text = """# Comma-delimited file
# FORMAT:   Team number,alias
10-3905,Test School 1
10-3906, Test School 2
10-9999
10-3905,Duplicate

"""
    assert parse_alias_file(text) == {"10-3905": "Test School 1", "10-3906": "Test School 2"}


def test_parse_legacy_team_file():
    assert parse_team_file("# own teams\n10-3905\n\n10-3906\n10-3905\n") == ["10-3905", "10-3906"]
