import re
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import update

from app.config import Settings
from app.devices import (CODE_MAX_ATTEMPTS, CodeCheck, DeviceStore, RateLimited, _now, describe_ua,
                         devices, email_codes, normalize_email)
from app.mail import ConsoleMailer, SesMailer, SmtpMailer, build_mailer
from app.main import create_app
from app.store import SnapshotStore
from conftest import FIXTURES

TOKEN = "test-bootstrap-token-0123456789"


class FakeMailer:
    description = "fake"

    def __init__(self):
        self.sent = []

    def send(self, to, subject, text):
        self.sent.append((to, subject, text))

    def last_code(self, to):
        for addr, subject, _ in reversed(self.sent):
            if addr == to and "code" in subject:
                return re.search(r"\b(\d{6})\b", subject).group(1)
        raise AssertionError(f"no code sent to {to}")


@pytest.fixture
def site(tmp_path):
    """Returns a factory for 'browsers': separate clients sharing one database and mailer."""
    mailer = FakeMailer()
    settings = Settings(_env_file=None, scrape_mode="replay", capture_set=str(FIXTURES), replay_speed=1000,
                        database_url=f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}",
                        admin_bootstrap_token=TOKEN, admin_notify_email="admin@example.com")
    clients = []

    def browser(ua="Mozilla/5.0 (Windows NT 10.0) Chrome/130.0 Safari/537.36"):
        c = TestClient(create_app(settings, mailer=mailer), follow_redirects=False, headers={"User-Agent": ua})
        c.__enter__()
        clients.append(c)
        return c

    browser.mailer = mailer
    yield browser
    for c in clients:
        c.__exit__(None, None, None)


def register(client, mailer, email):
    r = client.post("/register", data={"email": email})
    assert r.status_code == 303 and r.headers["location"] == "/verify", r.text
    r = client.post("/verify", data={"code": mailer.last_code(email)})
    assert r.status_code == 303 and r.headers["location"] == "/pending", r.text
    return r


def make_admin(site, email="admin@example.com"):
    admin = site()
    register(admin, site.mailer, email)
    r = admin.post("/admin/claim", data={"token": TOKEN})
    assert r.status_code == 303 and r.headers["location"] == "/admin"
    return admin


def device_id(admin, email):
    page = admin.get("/admin").text
    m = re.search(rf'{re.escape(email)}.*?/admin/devices/(\d+)/', page, re.S)
    assert m, f"{email} not on the admin page"
    return int(m.group(1))


def test_anonymous_visitors_are_sent_to_register(site):
    c = site()
    assert c.get("/healthz").json() == {"status": "ok"}
    assert c.get("/static/style.css").status_code == 200
    r = c.get("/")
    assert r.status_code == 303 and r.headers["location"] == "/register"
    assert c.get("/admin").headers["location"] == "/register"
    assert c.get("/api/scores").status_code == 401
    assert c.get("/api/status").status_code == 401
    assert c.get("/events").status_code == 401
    assert c.get("/partials/board", headers={"HX-Request": "true"}).headers["HX-Redirect"] == "/register"
    assert "Request access" in c.get("/register").text


def test_register_verify_approve_revoke(site):
    viewer = site("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Safari/604.1")
    viewer.post("/register", data={"email": "  Coach@Example.COM "})
    assert "coach@example.com" in viewer.get("/verify").text
    code = site.mailer.last_code("coach@example.com")

    wrong = "000000" if code != "000000" else "111111"
    r = viewer.post("/verify", data={"code": wrong})
    assert r.status_code == 400 and "Check the email and try again" in r.text

    r = viewer.post("/verify", data={"code": f"{code[:3]} {code[3:]}"})  # spaces are ignored
    assert r.status_code == 303 and r.headers["location"] == "/pending"
    assert "cpsb_device" in viewer.cookies

    # The admin is told about the new device.
    to, subject, body = site.mailer.sent[-1]
    assert to == "admin@example.com" and "coach@example.com" in subject
    assert "Safari on iOS" in body and "/admin" in body

    # Pending: the scoreboard redirects to the waiting page, which polls for approval.
    assert viewer.get("/").headers["location"] == "/pending"
    assert viewer.get("/api/scores").status_code == 403
    assert "Waiting for approval" in viewer.get("/pending").text
    assert viewer.get("/pending/status").status_code == 204

    admin = make_admin(site)
    page = admin.get("/admin").text
    assert "coach@example.com" in page and "Safari on iOS" in page
    vid = device_id(admin, "coach@example.com")
    assert admin.post(f"/admin/devices/{vid}/approve").status_code == 303

    assert viewer.get("/pending/status").headers["HX-Redirect"] == "/"
    dash = viewer.get("/")
    assert dash.status_code == 200 and "coach@example.com" in dash.text and 'href="/admin"' not in dash.text
    assert viewer.get("/api/scores").status_code == 200
    assert viewer.get("/admin").status_code == 403

    admin.post(f"/admin/devices/{vid}/label", data={"label": "Coach Smith"})
    assert "Coach Smith" in viewer.get("/").text

    admin.post(f"/admin/devices/{vid}/revoke")
    assert viewer.get("/").headers["location"] == "/blocked"
    assert viewer.get("/api/scores").status_code == 403
    assert "revoked" in viewer.get("/blocked").text


def test_admin_claim_requires_registration_and_the_right_token(site):
    c = site()
    assert "Register this browser" in c.get("/admin/claim").text
    assert c.post("/admin/claim", data={"token": TOKEN}).status_code == 400
    register(c, site.mailer, "someone@example.com")
    assert c.post("/admin/claim", data={"token": "wrong-token-wrong-token"}).status_code == 403
    assert c.get("/").headers["location"] == "/pending"  # still just pending
    assert c.post("/admin/claim", data={"token": TOKEN}).headers["location"] == "/admin"
    assert c.get("/").status_code == 200 and 'href="/admin"' in c.get("/").text


def test_admin_claim_is_rate_limited(site):
    c = site()  # each wrong token costs ~1 s by design
    register(c, site.mailer, "guesser@example.com")
    for _ in range(5):
        assert c.post("/admin/claim", data={"token": "wrong-token-wrong-token"}).status_code == 403
    r = c.post("/admin/claim", data={"token": TOKEN})  # even the right token, until the window passes
    assert r.status_code == 429 and "15 minutes" in r.text


def test_approved_viewer_is_emailed(site):
    viewer = site()
    register(viewer, site.mailer, "coach@example.com")
    admin = make_admin(site)
    admin.post(f"/admin/devices/{device_id(admin, 'coach@example.com')}/approve")
    to, subject, body = site.mailer.sent[-1]
    assert to == "coach@example.com" and "approved" in subject and "http://testserver/" in body


def test_admin_cannot_lock_themselves_out(site):
    admin = make_admin(site)
    me = device_id(admin, "admin@example.com")
    assert admin.post(f"/admin/devices/{me}/revoke").status_code == 400
    assert admin.post(f"/admin/devices/{me}/delete").status_code == 400
    assert admin.post("/admin/devices/9999/approve").status_code == 404
    assert admin.post(f"/admin/devices/{me}/explode").status_code == 404


def test_cross_site_posts_are_refused(site):
    c = site()
    r = c.post("/register", data={"email": "x@example.com"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert c.post("/register", data={"email": "x@example.com"},
                  headers={"Origin": "http://testserver"}).status_code == 303


def test_bad_email_and_resend_cooldown(site):
    c = site()
    assert c.post("/register", data={"email": "not-an-email"}).status_code == 400
    assert c.post("/register", data={"email": "a@example.com"}).status_code == 303
    r = c.post("/register", data={"email": "a@example.com"})
    assert r.status_code == 429 and "30 seconds" in r.text


def test_failed_email_send_is_reported(site):
    c = site()

    def boom(*a):
        raise OSError("smtp down")

    site.mailer.send = boom
    r = c.post("/register", data={"email": "a@example.com"})
    assert r.status_code == 502 and "send the email" in r.text
    assert "cpsb_reg" not in c.cookies


def test_forget_clears_the_device_cookie(site):
    c = site()
    register(c, site.mailer, "a@example.com")
    r = c.post("/forget")
    assert r.headers["location"] == "/register" and "cpsb_device" not in c.cookies


def test_expired_devices_must_register_again(site, tmp_path):
    c = site()
    register(c, site.mailer, "a@example.com")
    store = SnapshotStore(f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}")
    with store.engine.begin() as conn:
        conn.execute(update(devices).values(expires_at=_now() - timedelta(minutes=1)))
    store.close()
    assert c.get("/").headers["location"] == "/register"


# --- DeviceStore rules ---

@pytest.fixture
def store():
    s = SnapshotStore("sqlite://")
    yield DeviceStore(s)
    s.close()


def backdate_codes(ds, minutes):
    # Python-side arithmetic: SQLite stores these datetimes as text, so SQL subtraction would corrupt them.
    with ds.engine.begin() as conn:
        for row in conn.execute(email_codes.select()).all():
            conn.execute(update(email_codes).where(email_codes.c.id == row.id)
                         .values(created_at=row.created_at - timedelta(minutes=minutes)))


def test_code_rate_limits(store):
    store.issue_code("a@example.com", "1.1.1.1")
    with pytest.raises(RateLimited, match="30 seconds"):
        store.issue_code("a@example.com", "1.1.1.1")
    backdate_codes(store, 1)
    store.issue_code("a@example.com", "1.1.1.1")
    backdate_codes(store, 1)
    store.issue_code("a@example.com", "1.1.1.1")
    backdate_codes(store, 1)
    with pytest.raises(RateLimited, match="15 minutes"):
        store.issue_code("a@example.com", "1.1.1.1")
    backdate_codes(store, 20)
    store.issue_code("a@example.com", "1.1.1.1")  # window passed


def test_code_ip_limit(store):
    for i in range(10):
        store.issue_code(f"user{i}@example.com", "9.9.9.9")
    with pytest.raises(RateLimited, match="network"):
        store.issue_code("another@example.com", "9.9.9.9")
    store.issue_code("another@example.com", "8.8.8.8")


def test_code_expiry_and_lockout(store):
    issued = store.issue_code("a@example.com", "")
    for _ in range(CODE_MAX_ATTEMPTS - 1):
        assert store.check_code(issued.reg_token, "bad")[0] == CodeCheck.WRONG
    assert store.check_code(issued.reg_token, "bad")[0] == CodeCheck.LOCKED
    assert store.check_code(issued.reg_token, issued.code)[0] == CodeCheck.LOCKED  # even the right one
    assert store.pending_email(issued.reg_token) is None

    issued = store.issue_code("b@example.com", "")
    with store.engine.begin() as conn:
        conn.execute(update(email_codes).where(email_codes.c.email == "b@example.com")
                     .values(expires_at=_now() - timedelta(seconds=1)))
    assert store.check_code(issued.reg_token, issued.code) == (CodeCheck.EXPIRED, "b@example.com")

    backdate_codes(store, 1)
    issued = store.issue_code("c@example.com", "")
    assert store.check_code(issued.reg_token, issued.code) == (CodeCheck.OK, "c@example.com")
    assert store.check_code(issued.reg_token, issued.code)[0] == CodeCheck.MISSING  # single use
    assert store.check_code(None, "123456")[0] == CodeCheck.MISSING


def test_tokens_are_stored_hashed(store):
    token, device = store.create_device("a@example.com", "1.2.3.4", "ua")
    with store.engine.connect() as conn:
        stored = conn.execute(devices.select()).one()
    assert token not in (stored.token_hash,) and len(stored.token_hash) == 64
    assert store.lookup(token).id == device.id
    assert store.lookup("not-a-token") is None


def test_approval_resets_lifetime(store):
    _, d = store.create_device("a@example.com", "", "")
    with store.engine.begin() as conn:
        conn.execute(update(devices).values(expires_at=_now() + timedelta(days=1)))
    store.approve(d.id)
    assert store.get(d.id).approved
    assert (store.get(d.id).expires_at - store.get(d.id).approved_at).days == 365


@pytest.mark.parametrize("raw,expected", [
    ("  Coach@Example.COM ", "coach@example.com"), ("bad", None), ("a@b", None), ("a b@c.com", None),
])
def test_normalize_email(raw, expected):
    assert normalize_email(raw) == expected


@pytest.mark.parametrize("ua,expected", [
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36", "Chrome on Windows"),
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Version/17.0 Mobile Safari/604.1", "Safari on iOS"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) Gecko/20100101 Firefox/131.0", "Firefox on macOS"),
    ("Mozilla/5.0 (Windows NT 10.0) Chrome/130.0 Safari/537.36 Edg/130.0", "Edge on Windows"),
    ("curl/8.4.0", "curl"), ("", "unknown browser"),
])
def test_describe_ua(ua, expected):
    assert describe_ua(ua) == expected


# --- Settings and mail backends ---

def test_prod_requires_auth_and_a_long_token():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="prod", auth_enabled=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, admin_bootstrap_token="short")
    assert Settings(_env_file=None, app_env="prod").secure_cookies


def test_mail_backend_selection():
    assert isinstance(build_mailer(Settings(_env_file=None)), ConsoleMailer)
    assert isinstance(build_mailer(Settings(_env_file=None, smtp_host="mailpit")), SmtpMailer)
    assert isinstance(build_mailer(Settings(_env_file=None, app_env="prod")), SesMailer)


def test_smtp_mailer_builds_the_message(monkeypatch):
    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            sent.append((host, port))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def send_message(self, msg):
            sent.append(msg)

    monkeypatch.setattr("app.mail.smtplib.SMTP", FakeSMTP)
    SmtpMailer("mailpit", 1025, "CP <noreply@x.com>").send("a@b.com", "Hi", "Body")
    assert sent[0] == ("mailpit", 1025)
    assert sent[1]["To"] == "a@b.com" and sent[1]["From"] == "CP <noreply@x.com>"


def test_ses_mailer_calls_send_email():
    calls = []
    m = SesMailer.__new__(SesMailer)
    m.sender = "CP <noreply@x.com>"
    m.client = type("C", (), {"send_email": lambda self, **kw: calls.append(kw)})()
    m.send("a@b.com", "Subject", "Body")
    assert calls[0]["Destination"] == {"ToAddresses": ["a@b.com"]}
    assert calls[0]["Content"]["Simple"]["Subject"]["Data"] == "Subject"
