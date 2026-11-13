# CyberPatriot Scoreboard

A containerized web dashboard for following teams on the public CyberPatriot
scoreboard. It polls the scoreboard API once a minute and ranks every team
overall, by division, by state, and by state within division.

It's live (IP-allowlisted for now) and deployed automatically from `master` to
AWS. The original command-line bot that posts to X lives in [legacy/](legacy/).

## Roadmap

The plan is tracked in [GitHub Issues](https://github.com/mwinn53/cpscoreboard/issues),
grouped by [milestone](https://github.com/mwinn53/cpscoreboard/milestones). The agreed
order is M4 → M3b → M5 → M6 → M7, because the admin settings need M4's admin login.

| Milestone | Status | What it covers |
|---|---|---|
| [M1 – Restructure & dev loop](https://github.com/mwinn53/cpscoreboard/milestone/6) | ✅ Done ([#1](https://github.com/mwinn53/cpscoreboard/pull/1)) | Legacy code moved, scraper ported with tests, dev container, capture/replay |
| [M2 – Infra & pipeline](https://github.com/mwinn53/cpscoreboard/milestone/7) | ✅ Done ([#1](https://github.com/mwinn53/cpscoreboard/pull/1), [#3](https://github.com/mwinn53/cpscoreboard/pull/3)) | Terraform on EC2, GitHub Actions → ECR → SSM deploy, Caddy TLS |
| [M3a – Persistence & live updates](https://github.com/mwinn53/cpscoreboard/milestone/8) | ✅ Done ([#2](https://github.com/mwinn53/cpscoreboard/pull/2)) | SQLite change-only snapshots, restore on restart, SSE, change indicators |
| [M4 – Registration & approval](https://github.com/mwinn53/cpscoreboard/milestone/1) | 🚧 In progress | Email code → pending device → admin approval; gate the site; then open the allowlist |
| [M3b – Admin settings](https://github.com/mwinn53/cpscoreboard/milestone/2) | Planned | Watchlist, aliases and collection filter in the UI; legacy data import; Alembic |
| [M5 – X notifier](https://github.com/mwinn53/cpscoreboard/milestone/3) | Planned | Legacy `tweet()` behind a notifier interface |
| [M6 – History charts](https://github.com/mwinn53/cpscoreboard/milestone/4) | Planned | Per-team score/place charts; per-team detail data |
| [M7 – Analysis](https://github.com/mwinn53/cpscoreboard/milestone/5) | Planned | Analysis features; **season-end data retention (time-sensitive)** |

Issues labelled [`time-sensitive`](https://github.com/mwinn53/cpscoreboard/labels/time-sensitive)
have a real-world deadline, such as the scoreboard being taken down after the season.

## Layout

| Path | Purpose |
|---|---|
| `app/scraper.py` | Parses `scores.php` JSON into ranked `TeamScore` rows |
| `app/sources.py` | Where data comes from: `live`, `capture` (live + save changes), `replay` |
| `app/poller.py` | Background poll loop: change detection, backoff, storing changes, change indicators |
| `app/store.py` | SQLite (SQLAlchemy Core) history: `board_updates` + change-only `team_snapshots` |
| `app/events.py` | Server-sent events (`/events`) that tell open dashboards to refresh |
| `app/collection.py` | Collection filter: which teams are kept (locations, divisions, watched teams) |
| `app/web.py`, `app/templates/` | Dashboard (htmx) and the HTTP endpoints below |
| `tests/fixtures/` | Real scoreboard responses from season 17 (2024) and season 19 (2026) |
| `legacy/` | The original X-posting bot, kept for reference and the M3b/M5 ports |

### Endpoints

| Path | Returns |
|---|---|
| `/` | Dashboard: overall, division, state, and state-within-division rankings |
| `/events` | Server-sent events; a `board` event whenever the scoreboard changes |
| `/api/scores` | The current collected board as JSON |
| `/api/teams/{team}/history` | A team's stored snapshots, oldest first (`?limit=`, default 1000) |
| `/healthz` | Health check used by Docker and the deploy |
| `/api/docs` | Interactive API docs (dev only) |

## Configuration

All settings are environment variables; see [.env.example](.env.example).

| Variable | Default | Notes |
|---|---|---|
| `APP_ENV` | `dev` | `prod` refuses any `SCRAPE_MODE` other than `live` |
| `SCRAPE_MODE` | `live` | `live`, `capture`, or `replay` |
| `POLL_INTERVAL` | `60` | Seconds between polls |
| `DATA_DIR` | `data` (`/data` in the image) | Where the SQLite database lives |
| `DATABASE_URL` | — | Override the database. The default is `sqlite:///<DATA_DIR>/cpscoreboard.db`; in replay mode it's an in-memory database, so replays never mix into real history |
| `CAPTURE_SET` | — | Replay: folder under `captures/`, or any folder path |
| `REPLAY_SPEED` | `1` | e.g. `20` plays an hour of captures in 3 minutes |
| `REPLAY_LOOP` | `false` | Restart the replay when it ends |
| `COLLECT_LOCATIONS` | — (all) | Comma-separated locations to keep, e.g. `VA,MD,DC` |
| `COLLECT_DIVISIONS` | — (all) | Comma-separated divisions to keep, e.g. `Open,Middle School` |
| `WATCH_TEAMS` | — | Comma-separated team numbers to pin; always collected (temporary; moves to the database in M3b) |

### Access control

The scoreboard is private. There are no passwords. A visitor registers a browser
(a **device**) instead:

1. **`/register`**: enter an email address. A 6-digit code is emailed; it's valid
   for 10 minutes, with 5 attempts. Rate limits: 3 codes per address per 15 minutes,
   one every 30 seconds, and 10 per IP per hour.
2. **`/verify`**: entering the code creates a *pending* device and sets a long-lived,
   HttpOnly cookie. Only a hash of the cookie is stored. The admin is emailed if
   `ADMIN_NOTIFY_EMAIL` is set.
3. **`/pending`**: waits, polling every 10 seconds, until the admin approves this
   browser, then goes on to the scoreboard. Approval lasts `DEVICE_LIFETIME_DAYS`
   (365) from the approval date.
4. **`/admin`**: approve, deny or revoke, label, delete, or make another device an
   admin. Each device shows its browser and IP when registered and when last seen,
   and is flagged if the browser has changed. Revoking takes effect on the next
   request; an open live-update stream closes within about 20 seconds.

**Becoming admin:** register normally, then open **`/admin/claim`** and enter
`ADMIN_BOOTSTRAP_TOKEN`. In production, that token is the SSM SecureString
`/cpscoreboard/env/ADMIN_BOOTSTRAP_TOKEN`:

```sh
aws ssm get-parameter --name /cpscoreboard/env/ADMIN_BOOTSTRAP_TOKEN --with-decryption --query Parameter.Value --output text
```

`/healthz` stays public and returns only `{"status": "ok"}`. Everything else needs
an approved device; detailed status is at `/api/status`. In dev you can set
`AUTH_ENABLED=false` to skip all this; prod refuses to start that way.

| Variable | Default | Notes |
|---|---|---|
| `AUTH_ENABLED` | `true` | Dev only may set `false` |
| `ADMIN_BOOTSTRAP_TOKEN` | — | At least 16 characters; unset means nobody can claim admin |
| `ADMIN_NOTIFY_EMAIL` | — | Where "waiting for approval" emails go |
| `DEVICE_LIFETIME_DAYS` | `365` | |
| `MAIL_BACKEND` | `auto` | `auto`: SMTP if `SMTP_HOST` is set, SES in prod, otherwise the console log |
| `MAIL_FROM` | `noreply@localhost` | Must be on the SES-verified domain in prod |

### What gets stored

Each time the board changes, the app records one `board_updates` row with the time
and board size. It then writes a `team_snapshots` row for each **collected** team
whose score, images, warnings, score time or any place changed. Play time alone
doesn't trigger a row. With the filter limited to one state and division, that
means tens of rows per round, not thousands. On restart, the dashboard reloads the
last known board from the database instead of starting empty.

### Collection filter

`COLLECT_LOCATIONS` and `COLLECT_DIVISIONS` limit which teams the app keeps in
memory and in the database (M3b moves them into the admin UI). They're case-insensitive. When
both are set, a team must match both. When neither is set, every team is kept.

Places are computed on the **full** board before filtering, so a kept team still
shows its real national, division and state places. Watched teams are always
kept. Dev captures still save the full raw response, so a replay ranks teams the
same way the live board does; at about 25–70 KB per changed poll, the full
response is small.

## Development

### In the dev container (recommended)

Open the repo in VS Code and run **Dev Containers: Reopen in Container**. This
starts the app container plus [Mailpit](http://localhost:8025), which will catch
registration emails (M4).

```sh
uvicorn --factory app.main:create_app --reload --host 0.0.0.0 --port 8080
pytest
```

### Without Docker

```sh
python -m venv .venv
.venv/Scripts/activate        # Windows; use .venv/bin/activate on macOS/Linux
pip install -e ".[dev]"
uvicorn --factory app.main:create_app --reload --port 8080
```

### Capturing and replaying the live scoreboard

During a competition round, record the scoreboard:

```sh
SCRAPE_MODE=capture uvicorn --factory app.main:create_app --port 8080
```

Each poll whose data changed is saved as
`captures/<session>/<YYYYmmddTHHMMSSZ>.json.gz` (about 25–70 KB each). Unchanged
polls aren't saved. `captures/` is gitignored; copy any sets you want to keep
into `tests/fixtures/`.

Play a capture back at any time, with the original gaps between snapshots:

```sh
SCRAPE_MODE=replay CAPTURE_SET=2026-11-13_194314 REPLAY_SPEED=20 \
  uvicorn --factory app.main:create_app --port 8080
```

`CAPTURE_SET=tests/fixtures` replays the committed fixtures.

On Windows PowerShell, set variables first instead of using the inline `VAR=x` form:
`$env:SCRAPE_MODE="replay"; $env:CAPTURE_SET="tests/fixtures"`.

## Production image

```sh
docker build -t cpscoreboard .
docker run -p 8080:8080 -v cpsb-data:/data cpscoreboard
```

The default build target is `prod`. It runs as a non-root user, has a
`/healthz` health check, and is pinned to `APP_ENV=prod`, `SCRAPE_MODE=live`,
so it never saves pages.

## Deployment

Every push to `master` runs the tests and builds an arm64 image, then deploys it
to a single EC2 instance in us-east-1, behind Caddy for HTTPS. Other branches and
pull requests only run CI. See [infra/README.md](infra/README.md) for the one-time
Terraform and GitHub setup and for operations.

App settings reach the container from SSM Parameter Store (`/cpscoreboard/env/<KEY>`).
Terraform manages the non-secret settings. Add secrets by hand as SecureString
parameters under the same path, so they never land in Terraform state. Until M4 gates
the site, the security group only admits `allowed_cidrs` (see [#11](https://github.com/mwinn53/cpscoreboard/issues/11)).
Outbound email uses SES on the `savannahrivertech.com` domain (`infra/ses.tf`).

| Path | Purpose |
|---|---|
| `infra/` | Terraform: EC2, Elastic IP, `/data` volume and snapshots, ECR, IAM/OIDC, logs, SSM settings |
| `deploy/` | Production compose file, Caddyfile, and the SSM deploy scripts |
| `.github/workflows/` | `ci.yml` (tests, plus an image build on PRs) and `deploy.yml` (master → AWS) |
