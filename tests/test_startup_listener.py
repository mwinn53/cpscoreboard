"""Startup listener Lambda (infra/lambda/startup_listener.py, #50), with fake AWS clients."""

import importlib.util
import time
import urllib.parse
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "startup_listener", Path(__file__).parents[1] / "infra" / "lambda" / "startup_listener.py")


class NotFound(Exception):
    pass


class FakeSSM:
    class exceptions:
        ParameterNotFound = NotFound

    def __init__(self):
        self.params = {}

    def get_parameter(self, Name, WithDecryption=False):
        if Name not in self.params:
            raise NotFound(Name)
        return {"Parameter": {"Value": self.params[Name]}}

    def put_parameter(self, Name, Value, Overwrite, Type):
        self.params[Name] = Value


class FakeEC2:
    def __init__(self, state):
        self.state, self.started = state, 0

    def describe_instances(self, InstanceIds):
        return {"Reservations": [{"Instances": [{"State": {"Name": self.state}}]}]}

    def start_instances(self, InstanceIds):
        self.started += 1
        self.state = "pending"


class FakeSES:
    def __init__(self):
        self.sent = []

    def send_email(self, **kw):
        self.sent.append(kw)


class FakeLambda:
    def get_function_url_config(self, FunctionName):
        return {"FunctionUrl": "https://abc.lambda-url.us-east-1.on.aws/"}


class Context:
    function_name = "cpscoreboard-startup-listener"


@pytest.fixture
def sl(monkeypatch):
    monkeypatch.setenv("INSTANCE_ID", "i-123")
    monkeypatch.setenv("MAIL_FROM", "noreply@example.org")
    monkeypatch.setenv("MAIL_TO", "admin@example.org")
    monkeypatch.setenv("SITE_URL", "https://scores.example.org")
    mod = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(mod)
    mod.fakes = {"ssm": FakeSSM(), "ec2": FakeEC2("stopped"), "ses": FakeSES(), "lambda": FakeLambda()}
    mod._clients.update(mod.fakes)
    return mod


def test_tokens(sl):
    key = b"k" * 32
    t = sl.make_token(key)
    assert sl.check_token(key, t)
    assert not sl.check_token(b"x" * 32, t)                          # someone else's key
    assert not sl.check_token(key, t[:-1] + ("0" if t[-1] != "0" else "1"))  # tampered
    assert not sl.check_token(key, sl.make_token(key, now=time.time() - 8 * 86400))  # expired
    assert not sl.check_token(key, "garbage") and not sl.check_token(key, "")


def test_daily_check_emails_once_per_stopped_period(sl, monkeypatch):
    up = {"value": (False, 0)}
    monkeypatch.setattr(sl, "scoreboard_up", lambda: up["value"])
    assert sl.handler({}, Context())["action"] == "scoreboard still down"
    up["value"] = (True, 1931)
    r = sl.handler({}, Context())
    assert r["action"] == "emailed" and len(sl.fakes["ses"].sent) == 1
    body = sl.fakes["ses"].sent[0]["Message"]["Body"]["Text"]["Data"]
    assert "https://abc.lambda-url.us-east-1.on.aws/?t=" in body and "1931 teams" in body
    assert sl.handler({}, Context())["action"] == "already emailed" and len(sl.fakes["ses"].sent) == 1
    sl.fakes["ec2"].state = "running"
    assert sl.handler({}, Context())["action"] == "nothing to watch"   # and the next stop watches again
    sl.fakes["ec2"].state = "stopped"
    assert sl.handler({}, Context())["action"] == "emailed" and len(sl.fakes["ses"].sent) == 2


def test_the_link_needs_a_post_to_start(sl):
    token = sl.make_token(sl.signing_key())
    get = sl.handler({"requestContext": {"http": {"method": "GET"}}, "queryStringParameters": {"t": token}}, Context())
    assert get["statusCode"] == 200 and "Start the server" in get["body"] and sl.fakes["ec2"].started == 0
    bad = sl.handler({"requestContext": {"http": {"method": "POST"}}, "body": "t=nope"}, Context())
    assert bad["statusCode"] == 403 and sl.fakes["ec2"].started == 0
    post = sl.handler({"requestContext": {"http": {"method": "POST"}},
                       "body": urllib.parse.urlencode({"t": token})}, Context())
    assert post["statusCode"] == 200 and "starting" in post["body"] and sl.fakes["ec2"].started == 1
    again = sl.handler({"requestContext": {"http": {"method": "POST"}},
                        "body": urllib.parse.urlencode({"t": token})}, Context())
    assert "already pending" in again["body"] and sl.fakes["ec2"].started == 1


def test_signing_key_is_created_once(sl):
    k1, k2 = sl.signing_key(), sl.signing_key()
    assert k1 == k2 and len(k1) >= 32
    assert "/cpscoreboard/startup-listener/signing-key" in sl.fakes["ssm"].params
