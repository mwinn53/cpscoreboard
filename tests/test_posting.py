"""Posting about watched teams (M5): planner, limits, X signing, credentials, admin page."""

import asyncio
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import httpx
from cryptography.fernet import Fernet

from app.board_config import BoardConfig
from app.posting import (KINDS, Credentials, LogNotifier, Post, Poster, PostPlanner, PostSettings, XNotifier,
                         oauth1_header, ordinal)
from app.scraper import TeamScore
from app.secret_box import SecretBox
from app.store import SnapshotStore
from test_auth import make_admin, site  # noqa: F401 (fixture)

ET = ZoneInfo("America/New_York")
AT = datetime(2026, 11, 14, 15, 5, tzinfo=UTC)  # 10:05 AM EST
H = 3600


def team(play, score, nat=10, st=3, number="19-1001"):
    return TeamScore(team_number=number, team_id=1, location="GA", division="Middle School", tier="",
                     images=3, play_time=play, score_time=play, ccs_score=score, adjustment=None, total=None,
                     code="", place_overall=nat, place_division=nat, place_state=st, place_state_division=st)


def kinds(posts):
    return [p.kind for p in posts]


def test_ordinal():
    assert [ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 101, 111)] == \
        ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "101st", "111th"]


def test_planner_follows_a_round():
    p, s, schools = PostPlanner(ET), PostSettings(), {"19-1001": "EMS"}
    assert p.observe([team(0, 0)], schools, s, AT) == []          # primes: listed, not playing yet
    on = p.observe([team(60, 5)], schools, s, AT)                  # starts playing
    assert kinds(on) == ["on_board"]
    assert on[0].text == "EMS (19-1001) is on the board at 10:05 AM with 5 points, 3rd in GA (Middle School)."
    assert p.observe([team(2 * H, 50, nat=8)], schools, s, AT) == []  # before 4 h: no play-by-play
    ch = p.observe([team(4 * H + 60, 80, nat=5, st=2)], schools, s, AT)
    assert kinds(ch) == ["change"]
    assert ch[0].text == "EMS (19-1001): +30 points to 80. Up 3 places nationally (now 5th). Up 1 place in GA (now 2nd)."
    assert kinds(p.observe([team(5 * H + 60, 80, nat=5, st=2)], schools, s, AT)) == ["hour_left"]
    up = p.observe([team(6 * H, 90, nat=4, st=2)], schools, s, AT)
    assert kinds(up) == ["time_up", "change"]
    assert p.observe([team(6 * H, 90, nat=4, st=2)], schools, s, AT) == []  # nothing new
    assert kinds(p.observe([team(30, 0)], schools, s, AT)) == ["on_board"]  # next round


def test_restart_mid_round_does_not_repeat_posts():
    p, s = PostPlanner(ET), PostSettings()
    assert p.observe([team(5 * H + 120, 80)], {}, s, AT) == []
    assert p.observe([team(5 * H + 180, 80)], {}, s, AT) == []
    assert "Team 19-1001" in p.observe([team(5 * H + 240, 85)], {}, s, AT)[0].text


def test_unchecked_kinds_are_dropped():
    p, s = PostPlanner(ET), PostSettings(kinds=set(KINDS) - {"on_board"})
    p.observe([team(0, 0)], {}, s, AT)
    assert p.observe([team(60, 5)], {}, s, AT) == []


def test_oauth1_signature_matches_the_documented_example():
    # The worked example from X's "Creating a signature" documentation.
    creds = {"x_api_key": "xvz1evFS4wEEPTGEFPHBog", "x_api_secret": "kAcSOqF21Fu85e7zjz7ZN2U4ZRhfV3WpwPAoE3Z7kBw",
             "x_access_token": "370773112-GmHxMAgYyLbNEtIKZeRNFsMKPR9EyMZeS9weJAEb",
             "x_access_secret": "LswwdoUaIvS8ltyTt5jkRh4J50vUPVVHtR2YPi5kE"}
    header = oauth1_header("POST", "https://api.twitter.com/1.1/statuses/update.json", creds,
                           nonce="kYjzVBB8Y0ZFabxSWbWovY3uYSQ2pTgmZeNu2VS4cg", timestamp=1318622958,
                           extra={"include_entities": "true",
                                  "status": "Hello Ladies + Gentlemen, a signed OAuth request!"})
    assert 'oauth_signature="hCtSmYh%2BiHYCEqBWrE7C7hYmtUk%3D"' in header
    assert "status" not in header  # signed, but not sent in the header


def test_x_notifier_sends_json_with_oauth():
    seen = {}

    def handler(request: httpx.Request):
        seen["auth"], seen["body"] = request.headers["Authorization"], request.content
        return httpx.Response(201, json={"data": {"id": "123", "text": "hi"}})

    creds = {k: "v" for k in ("x_api_key", "x_api_secret", "x_access_token", "x_access_secret")}

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await XNotifier(client, creds).post("hi")

    assert asyncio.run(go()) == "123"
    assert seen["auth"].startswith("OAuth ") and seen["body"] == b'{"text":"hi"}'


def _poster(mode="x"):
    store = SnapshotStore("sqlite://")
    board = BoardConfig(store)
    board.seed(["19-1001"], "", "", "", "", "Watched", "")
    sent = []

    class Fake:
        target = "x"

        async def post(self, text):
            sent.append(text)
            return f"id{len(sent)}"

    poster = Poster(store, board, SecretBox(Fernet.generate_key().decode()), None, ET,
                    notifier_factory=lambda s: (Fake() if s.mode == "x" else LogNotifier() if s.mode == "dry_run" else None))
    PostSettings(mode=mode, per_hour=2, per_day=3).save(board)
    return poster, sent, store


def test_limits_skip_and_log():
    poster, sent, store = _poster()
    statuses = [asyncio.run(poster.send(Post("change", "19-1001", f"post {i}"))) for i in range(4)]
    assert statuses == ["sent", "sent", "skipped", "skipped"] and len(sent) == 2
    recent = poster.recent()
    assert recent[0].status == "skipped" and "limit reached" in recent[0].detail
    assert asyncio.run(poster.send(Post("test", "", "test"), limits=False)) == "sent"
    store.close()


def test_board_changed_posts_for_watched_teams_only():
    poster, sent, store = _poster()
    asyncio.run(poster.board_changed([team(0, 0), team(0, 0, number="19-9999")], AT))
    asyncio.run(poster.board_changed([team(60, 5), team(60, 5, number="19-9999")], AT))
    assert len(sent) == 1 and "19-1001" in sent[0]
    store.close()


def test_footer_and_length():
    poster, _, store = _poster()
    s = PostSettings(footer="#CyberPatriot")
    assert poster.compose("Hello", s) == "Hello #CyberPatriot"
    assert len(poster.compose("x" * 400, s)) == 280
    store.close()


def test_credentials_are_encrypted_at_rest():
    store = SnapshotStore("sqlite://")
    board = BoardConfig(store)
    creds = Credentials(board, SecretBox(Fernet.generate_key().decode()))
    creds.set("x_api_key", "abc")
    assert board.get_value("x_api_key") not in ("", "abc") and creds.get() is None  # three still missing
    for k in ("x_api_secret", "x_access_token", "x_access_secret"):
        creds.set(k, k)
    assert creds.get()["x_api_key"] == "abc"
    other = Credentials(board, SecretBox(Fernet.generate_key().decode()))  # wrong key
    assert other.get() is None
    store.close()


def test_configuration_page(site):  # noqa: F811
    admin = make_admin(site)
    page = admin.get("/admin/config")
    assert page.status_code == 200 and "Posting to X" in page.text and "SECRETS_KEY" in page.text
    assert 'href="/admin/config"' in admin.get("/admin").text
    r = admin.post("/admin/config/posting", data={"mode": "dry_run", "kinds": ["on_board", "time_up"],
                                                  "change_after_hours": "3", "per_hour": "5", "per_day": "15",
                                                  "footer": "#CP"})
    assert r.status_code == 303
    s = admin.app.state.poster.settings()
    assert (s.mode, s.kinds, s.change_after_hours, s.per_hour, s.per_day, s.footer) == \
        ("dry_run", {"on_board", "time_up"}, 3.0, 5, 15, "#CP")
    assert admin.post("/admin/config/x-credentials", data={"x_api_key": "k"}).status_code == 400  # no SECRETS_KEY
    admin.app.state.poster.box = SecretBox(Fernet.generate_key().decode())
    admin.app.state.poster.credentials.box = admin.app.state.poster.box
    assert admin.post("/admin/config/x-credentials", data={"x_api_key": "k"}).status_code == 303
    page = admin.get("/admin/config")
    assert "Some keys are missing" in page.text and 'value="k"' not in page.text
    assert admin.post("/admin/config/test-post", data={"text": "hello"}).status_code == 303
    assert "hello" in admin.get("/admin/config").text  # dry run shows in the log
    assert admin.post("/admin/config/posting", data={"mode": "bogus"}).status_code == 400
