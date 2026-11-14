"""Startup listener (issue #50): while the server is stopped, watch for the public
scoreboard to come back, then email the admin a link to start the server.

Runs in AWS Lambda (Python, standard library plus boto3), two ways:

* **Daily check** (EventBridge Scheduler): if the instance isn't stopped, there's
  nothing to watch, so it forgets any earlier email and returns. If it's stopped,
  it fetches the scores feed; "up" means a readable board with teams. The first
  time it sees the board up, it emails the admin (once per stopped period).
* **The link** (Lambda Function URL): ``GET ?t=<token>`` shows a confirmation page
  with a button; only the button's ``POST`` starts the instance. Mail scanners open
  links, so a GET never starts anything. Tokens are HMAC-signed and expire after
  ``TOKEN_DAYS``; the signing key is generated on first use and kept as an SSM
  SecureString, so no secret goes through Terraform.

Settings come from environment variables set by Terraform (infra/startup_listener.tf).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import os
import secrets
import time
import urllib.parse
import urllib.request

import boto3

INSTANCE_ID = os.environ.get("INSTANCE_ID", "")
SCOREBOARD_URL = os.environ.get("SCOREBOARD_URL", "https://scoreboard.uscyberpatriot.org/api/team/scores.php")
MAIL_FROM = os.environ.get("MAIL_FROM", "")
MAIL_TO = os.environ.get("MAIL_TO", "")
SITE_URL = os.environ.get("SITE_URL", "")
SITE_TITLE = os.environ.get("SITE_TITLE", "CyberPatriot scoreboard")
PARAM_PREFIX = os.environ.get("PARAM_PREFIX", "/cpscoreboard/startup-listener")
TOKEN_DAYS = int(os.environ.get("TOKEN_DAYS", "7"))

_clients: dict = {}


def client(name):
    if name not in _clients:
        _clients[name] = boto3.client(name)
    return _clients[name]


# --- state and signing key (SSM) ---

def _get_param(name, decrypt=False):
    try:
        return client("ssm").get_parameter(Name=f"{PARAM_PREFIX}/{name}", WithDecryption=decrypt)["Parameter"]["Value"]
    except client("ssm").exceptions.ParameterNotFound:
        return None


def _put_param(name, value, secure=False):
    client("ssm").put_parameter(Name=f"{PARAM_PREFIX}/{name}", Value=value, Overwrite=True,
                                Type="SecureString" if secure else "String")


def signing_key():
    key = _get_param("signing-key", decrypt=True)
    if not key:
        key = secrets.token_urlsafe(32)
        _put_param("signing-key", key, secure=True)
    return key.encode()


def make_token(key, now=None):
    expires = int((now or time.time()) + TOKEN_DAYS * 86400)
    payload = f"start:{INSTANCE_ID}:{expires}"
    sig = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=") + "." + sig


def check_token(key, token, now=None):
    """True if the token is ours, for this instance, and not expired."""
    try:
        b64, sig = token.split(".", 1)
        payload = base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4)).decode()
        action, instance, expires = payload.split(":")
    except (ValueError, UnicodeDecodeError):
        return False
    good = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()
    return (hmac.compare_digest(good, sig) and action == "start" and instance == INSTANCE_ID
            and int(expires) >= (now or time.time()))


# --- the daily check ---

def instance_state():
    r = client("ec2").describe_instances(InstanceIds=[INSTANCE_ID])
    return r["Reservations"][0]["Instances"][0]["State"]["Name"]


def scoreboard_up():
    """(up, team count): a readable board with at least one team."""
    req = urllib.request.Request(SCOREBOARD_URL, headers={"User-Agent": "cpscoreboard-startup-listener/1"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            doc = json.loads(resp.read())
    except Exception:
        return False, 0
    rows = doc.get("data") if isinstance(doc, dict) else doc
    teams = len(rows) if isinstance(rows, list) else 0
    return teams > 0, teams


def function_url(context):
    return client("lambda").get_function_url_config(FunctionName=context.function_name)["FunctionUrl"]


def send_email(link, teams):
    body = (f"The public CyberPatriot scoreboard is back up ({teams} teams on the board), and the "
            f"{SITE_TITLE} server is stopped.\n\n"
            f"To start the server, open this link and press the button (the link works for {TOKEN_DAYS} days):\n"
            f"{link}\n\n"
            f"The site ({SITE_URL}) is back a couple of minutes after starting. Its address doesn't change.\n"
            f"You won't get this email again until the server has run and been stopped again.\n")
    client("ses").send_email(Source=MAIL_FROM, Destination={"ToAddresses": [MAIL_TO]},
                             Message={"Subject": {"Data": f"{SITE_TITLE}: the public scoreboard is back"},
                                      "Body": {"Text": {"Data": body}}})


def daily_check(context):
    state = instance_state()
    if state != "stopped":
        if _get_param("notified"):
            _put_param("notified", "none")  # it ran again: a later stop starts a new watch
        return {"state": state, "action": "nothing to watch"}
    if (_get_param("notified") or "none") != "none":
        return {"state": state, "action": "already emailed"}
    up, teams = scoreboard_up()
    if not up:
        return {"state": state, "action": "scoreboard still down"}
    link = function_url(context) + "?" + urllib.parse.urlencode({"t": make_token(signing_key())})
    send_email(link, teams)
    _put_param("notified", str(int(time.time())))
    return {"state": state, "action": "emailed", "teams": teams}


# --- the link ---

def page(title, message, form_token=None, status=200):
    button = ""
    if form_token:
        button = (f'<form method="post"><input type="hidden" name="t" value="{html.escape(form_token)}">'
                  f'<button type="submit">Start the server</button></form>')
    doc = (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
           f'<meta name="viewport" content="width=device-width, initial-scale=1"><title>{html.escape(title)}</title>'
           f'<style>body{{font-family:system-ui,sans-serif;max-width:36rem;margin:3rem auto;padding:0 1rem;'
           f'line-height:1.5}}button{{font:inherit;padding:.6rem 1.2rem;border-radius:6px;border:0;'
           f'background:#1f5fbf;color:#fff;cursor:pointer}}</style></head><body>'
           f'<h1>{html.escape(title)}</h1><p>{message}</p>{button}</body></html>')
    return {"statusCode": status, "headers": {"Content-Type": "text/html; charset=utf-8",
                                               "Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
            "body": doc}


def web(event):
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    if method == "POST":
        raw = event.get("body") or ""
        if event.get("isBase64Encoded"):
            raw = base64.b64decode(raw).decode()
        token = urllib.parse.parse_qs(raw).get("t", [""])[0]
    else:
        token = (event.get("queryStringParameters") or {}).get("t", "")
    if not token or not check_token(signing_key(), token):
        return page("Link not valid", "This link is invalid or has expired. A new one is emailed when the "
                    "scoreboard is back and the server is stopped.", status=403)
    state = instance_state()
    site = html.escape(SITE_URL)
    if method != "POST":
        if state == "stopped":
            return page(f"Start {SITE_TITLE}?", "The server is stopped. Press the button to start it; the site "
                        f"comes back at {site} in a couple of minutes.", form_token=token)
        return page("Nothing to start", f"The server is already {html.escape(state)}. The site is at {site}.")
    if state == "stopped":
        client("ec2").start_instances(InstanceIds=[INSTANCE_ID])
        return page("Starting", f"The server is starting. The site will be back at <a href=\"{site}\">{site}</a> "
                    "in a couple of minutes.")
    return page("Nothing to start", f"The server is already {html.escape(state)}. The site is at {site}.")


def handler(event, context):
    if "requestContext" in event:  # Function URL
        return web(event)
    return daily_check(context)
