# CyberPatriot Scoreboard

A containerized web dashboard for following teams on the public CyberPatriot
scoreboard. It polls the scoreboard API once a minute and shows each team's
District, State and National placement, with live updates and change indicators.

It's live at <https://cpscores.savannahrivertech.com> (approved devices only) and deployed automatically from `master` to
AWS. The original command-line bot that posts to X lives in [legacy/](legacy/).

## Roadmap

The plan is tracked in [GitHub Issues](https://github.com/mwinn53/cpscoreboard/issues),
grouped by [milestone](https://github.com/mwinn53/cpscoreboard/milestones). M4 and M3b
are in production. Next up is M5 → M6 → M7; the time-sensitive season-end retention
([#20](https://github.com/mwinn53/cpscoreboard/issues/20)) comes first.

| Milestone | Status | What it covers |
|---|---|---|
| [M1 – Restructure & dev loop](https://github.com/mwinn53/cpscoreboard/milestone/6) | ✅ Done ([#1](https://github.com/mwinn53/cpscoreboard/pull/1)) | Legacy code moved, scraper ported with tests, dev container, capture/replay |
| [M2 – Infra & pipeline](https://github.com/mwinn53/cpscoreboard/milestone/7) | ✅ Done ([#1](https://github.com/mwinn53/cpscoreboard/pull/1), [#3](https://github.com/mwinn53/cpscoreboard/pull/3)) | Terraform on EC2, GitHub Actions → ECR → SSM deploy, Caddy TLS |
| [M3a – Persistence & live updates](https://github.com/mwinn53/cpscoreboard/milestone/8) | ✅ Done ([#2](https://github.com/mwinn53/cpscoreboard/pull/2)) | SQLite change-only snapshots, restore on restart, SSE, change indicators |
| [M4 – Registration & approval](https://github.com/mwinn53/cpscoreboard/milestone/1) | ✅ Live ([#27](https://github.com/mwinn53/cpscoreboard/pull/27), [#31](https://github.com/mwinn53/cpscoreboard/pull/31)); open: geolocation [#8](https://github.com/mwinn53/cpscoreboard/issues/8), prod checks [#9](https://github.com/mwinn53/cpscoreboard/issues/9), DNS [#10](https://github.com/mwinn53/cpscoreboard/issues/10) | Email code → pending device → admin approval; the whole site is gated |
| [M3b – Admin settings](https://github.com/mwinn53/cpscoreboard/milestone/2) | ✅ Live ([#29](https://github.com/mwinn53/cpscoreboard/pull/29), [#30](https://github.com/mwinn53/cpscoreboard/pull/30), [#32](https://github.com/mwinn53/cpscoreboard/pull/32)); open: Alembic [#16](https://github.com/mwinn53/cpscoreboard/issues/16) | Watchlist, district schools, collection filter, logos and legacy import on `/admin/board` |
| [M5 – X notifier](https://github.com/mwinn53/cpscoreboard/milestone/3) | Planned | Legacy `tweet()` behind a notifier interface |
| [M6 – History charts](https://github.com/mwinn53/cpscoreboard/milestone/4) | Planned | Per-team score/place charts; per-team detail data |
| [M7 – Analysis](https://github.com/mwinn53/cpscoreboard/milestone/5) | 🚧 Season archive live ([#34](https://github.com/mwinn53/cpscoreboard/pull/34)); rest planned | Analysis features; **season-end data retention (time-sensitive)** |

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
| `app/auth.py`, `app/devices.py` | Registration (email code), device approval, admin page, access checks |
| `app/board_config.py`, `app/admin_board.py` | Watchlist, district schools, collection filter and view defaults (database + admin page), legacy import |
| `app/branding.py` | Header logos, uploaded and cropped on the admin page, stored in the database |
| `app/archive.py`, `app/admin_archive.py` | Season archive: the full raw scoreboard, one file per day, and its admin page |
| `app/mail.py` | Email via SES (prod), SMTP/Mailpit (dev container), or the console log |
| `app/main.py`, `app/config.py` | App factory; settings from environment variables |
| `tests/fixtures/` | Real scoreboard responses from season 17 (2024) and season 19 (2026) |
| `legacy/` | The original X-posting bot, kept for reference and the M3b/M5 ports |

### Endpoints

| Path | Returns |
|---|---|
| `/` | Dashboard: the live board with National (division), State (within division) and District places; opens on the collected division and state |
| `/events` | Server-sent events; a `board` event whenever the scoreboard changes |
| `/api/status` | Poller, source, filter and database status |
| `/api/scores` | The current collected board as JSON |
| `/api/teams/{team}/history` | A team's stored snapshots, oldest first (`?limit=`, default 1000) |
| `/register`, `/verify`, `/pending` | Registration: email → code → waiting for approval (public) |
| `/admin`, `/admin/claim` | Device approval (admin only); claiming admin with the bootstrap token |
| `/admin/board` | Board settings (admin only): default view, watchlist, district schools, collection filter, bulk import, logos |
| `/admin/archive` | Season archive (admin only): one full scoreboard per day, downloadable |
| `/admin/server` | Public-scoreboard health and the outage alert; snapshot and shut down the server (admin only) |
| `/brand/left`, `/brand/right` | Header logos (public); placeholders until uploaded on `/admin/board` |
| `/healthz` | Public health check for Docker and the deploy; returns only `{"status": "ok"}` |
| `/api/docs` | Interactive API docs (dev only) |

Everything except `/healthz`, the registration pages and `/static` requires an
approved device (see [Access control](#access-control)).

### The dashboard

- **Filters** in the header: search, division, state and rows. The page opens on the
  default view set on `/admin/board`, and the address bar follows the filters, so a
  reload or a shared link keeps the view.
- **Columns:** School, score first, then a **Placement** group in the order:
  - **District**: place among the district schools' teams plus the watched teams, within the division.
  - **State**: place in the state, within the division.
  - **National**: place in the division, nationally.

  Each Placement header shows how many teams it ranks, e.g. **District (16)**, **State (22)**,
  **National (205)**. A count appears only when every team in the table shares one division
  (and, for State, one state); with the filter on All there's no single total.
  State, Division and Tier columns appear only when the filter is set to All.
- **Trends:** ▲▼ for place and +/− for score since the last change, in fixed slots so
  numbers line up.
- **Watched teams** are pinned under their own heading (default "Watchlist").
- **Live updates:** the board refreshes on every change (via `/events`) and every polling
  interval. Times are shown in `DISPLAY_TIMEZONE`.
- **Logos:** a square logo sits at each end of the header. Each can link somewhere:
  the CyberPatriot logo links to the public scoreboard, and the school logo's link is optional.

## Configuration

All settings are environment variables; see [.env.example](.env.example).

| Variable | Default | Notes |
|---|---|---|
| `APP_ENV` | `dev` | `prod` refuses any `SCRAPE_MODE` other than `live` |
| `LOG_LEVEL` | `INFO` | |
| `SCRAPE_MODE` | `live` | `live`, `capture`, or `replay` |
| `SCOREBOARD_URL` | the public `scores.php` API | |
| `POLL_INTERVAL` | `60` | Seconds between polls |
| `SITE_TITLE` | `EMS CyberPatriot Next Generation Scorebot` | Header, browser tab, and email subjects/sender name |
| `DISPLAY_TIMEZONE` | `America/New_York` | Times on the site; the database stays in UTC |
| `DATA_DIR` | `data` (`/data` in the image) | Where the SQLite database lives |
| `DATABASE_URL` | — | Override the database. The default is `sqlite:///<DATA_DIR>/cpscoreboard.db`; in replay mode it's an in-memory database, so replays never mix into real history |
| `ARCHIVE_ENABLED` | `true` | Save the full scoreboard once per day (see [Season archive](#season-archive)); always off in replay |
| `CAPTURE_DIR` | `captures` | Where capture mode saves, and where `CAPTURE_SET` names are looked up |
| `CAPTURE_SET` | — | Replay: folder under `CAPTURE_DIR`, or any folder path |
| `REPLAY_SPEED` | `1` | e.g. `20` plays an hour of captures in 3 minutes |
| `REPLAY_LOOP` | `false` | Restart the replay when it ends |
| `COLLECT_LOCATIONS` | — (all) | First start only: locations to keep, e.g. `VA,MD,DC` |
| `COLLECT_DIVISIONS` | — (all) | First start only: divisions to keep, e.g. `Open,Middle School` |
| `WATCH_TEAMS` | — | First start only: team numbers to pin; always collected |
| `DEFAULT_DIVISION`, `DEFAULT_STATE` | — | First start only: where the dashboard opens (`all`, or blank to follow the collection filter) |
| `WATCH_LABEL` | `Watchlist` | First start only: heading for the watched teams |
| `WATCH_SCHOOL` | — | First start only: School column for watched teams that aren't listed as district schools (e.g. `EMS`) |
| `WATCH_SCHOOL` | — | First start only: School column for watched teams not listed as district schools (e.g. `EMS`) |

The `COLLECT_*`, `WATCH_*` and `DEFAULT_*` settings only **seed** the database the first time the app starts. After that,
change them on the admin page (`/admin/board`); the env vars are ignored, and the
startup log says so.

### Access control

The scoreboard is private. There are no passwords. A visitor registers a browser
(a **device**) instead:

1. **`/register`**: enter an email address and your relationship to the team (free text,
   shown to the admin on `/admin` and in the approval email). A 6-digit code is emailed; it's valid
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
| `MAIL_BACKEND` | `auto` | `ses`, `smtp`, `console`, or `auto`: SMTP if `SMTP_HOST` is set, SES in prod, otherwise the console log |
| `MAIL_FROM` | `noreply@localhost` | Must be on the SES-verified domain in prod |
| `MAIL_FROM_NAME` | `SITE_TITLE` | Sender display name |
| `SMTP_HOST`, `SMTP_PORT` | —, `1025` | SMTP server (Mailpit in the dev container) |
| `AWS_REGION` | `us-east-1` | SES region |

### What gets stored

Each time the board changes, the app records one `board_updates` row with the time
and board size. It then writes a `team_snapshots` row for each **collected** team
whose score, images, warnings, score time or any place changed. Play time alone
doesn't trigger a row. With the filter limited to one state and division, that
means tens of rows per round, not thousands. On restart, the dashboard reloads the
last known board from the database instead of starting empty.

The schema comes from SQLAlchemy `create_all`, plus a small startup step that adds new
columns with defaults to existing tables. Anything more (renames, type changes) waits
for Alembic ([#16](https://github.com/mwinn53/cpscoreboard/issues/16)).

### Season archive

The public scoreboard is taken down after the season, and the database only keeps
history for collected teams. So the app also saves the **complete raw scoreboard**
(every team and division, the API's JSON, gzipped) to `<DATA_DIR>/archive/`, one
file per day: each time the board changes, that day's file is replaced, so it holds
the last board seen that day. On a competition day, that's the board as the round
closed. A day is about 70 KB.

Files are named like dev captures (`YYYYmmddTHHMMSSZ.json.gz`), so a folder of them
replays with `SCRAPE_MODE=replay CAPTURE_SET=<folder>`. Admins can download them at
`/admin/archive`. On the server they live on the `/data` volume, which has daily EBS
snapshots. Set `ARCHIVE_ENABLED=false` to turn this off; it's always off in replay mode.

### End of season: outage alert and shutdown

The app watches the public scoreboard. When it has been unavailable for **24 hours**
(`OUTAGE_ALERT_HOURS`), the admin (`ADMIN_NOTIFY_EMAIL`) gets one email per outage
recommending a shutdown, with links to download the archive and to `/admin/server`.
Monitoring starts **72 hours** (`OUTAGE_GRACE_HOURS`) after the competition starts,
which is recorded automatically the first time a board shows play time (or set it on
`/admin/server`). "Unavailable" means no usable board: a fetch error, an unexpected
response or an empty board.

**Snapshot and shut down** on `/admin/server` (type `SHUT DOWN` to confirm) takes a
final EBS snapshot of `/data` and then stops the EC2 instance. Stopping is
reversible: `aws ec2 start-instances --instance-ids <id>`. The instance role may only
snapshot its own data volume and stop its own instance (`infra/iam.tf`). Terraform
supplies `PUBLIC_URL`, `AWS_INSTANCE_ID` and `DATA_VOLUME_ID`.

### Collection filter

The collection filter (states/locations and divisions, set on `/admin/board`) limits
which teams the app stores as history in the database. The dashboard always shows the
full live board. It's case-insensitive. When
both are set, a team must match both. When neither is set, every team is kept.

Places are computed on the **full** board before filtering, so a kept team still
shows its real national, division and state places. Watched teams are always
kept. Changes take effect at once, without a restart; newly collected teams are
stored from the next poll. Narrowing the filter keeps existing history but stops
recording the dropped teams.

The **bulk import** on `/admin/board` takes the old bot's `runs/team` file (one team
number per line, added to the watchlist) and `runs/lookups` file (`team,school` per
line; added as district schools; the first name wins if a team is listed twice). `#` lines are comments, and
importing twice changes nothing. Dev captures still save the full raw response, so a replay ranks teams the
same way the live board does; at about 25–70 KB per changed poll, the full
response is small.

## Development

### In the dev container (recommended)

Open the repo in VS Code and run **Dev Containers: Reopen in Container**. This
starts the app container plus [Mailpit](http://localhost:8025), which catches
registration emails. Register at `/register`, read the code in Mailpit, then claim
admin at `/admin/claim` with the dev token `dev-admin-token-not-secret`.

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
parameters under the same path, so they never land in Terraform state. The site is
public at the network level (`allowed_cidrs`); access is controlled by device approval.
Outbound email uses SES on the `savannahrivertech.com` domain (`infra/ses.tf`).

| Path | Purpose |
|---|---|
| `infra/` | Terraform: EC2, Elastic IP, `/data` volume and snapshots, ECR, IAM/OIDC, logs, SSM settings |
| `deploy/` | Production compose file, Caddyfile, and the SSM deploy scripts |
| `.github/workflows/` | `ci.yml` (tests, plus an image build on PRs) and `deploy.yml` (master → AWS) |
