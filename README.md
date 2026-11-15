# CyberPatriot Scoreboard

A containerized web dashboard for following teams on the public CyberPatriot
scoreboard. It polls the scoreboard API once a minute and shows each team's
District, State and National placement, with live updates and change indicators.

It's live at <https://cpscores.savannahrivertech.com> (approved devices only) and deployed automatically from `master` to
AWS. The original command-line bot that posts to X lives in [legacy/](legacy/).

## Roadmap

The plan is tracked in [GitHub Issues](https://github.com/mwinn53/cpscoreboard/issues),
grouped by [milestone](https://github.com/mwinn53/cpscoreboard/milestones). M4, M3b and M6
are in production, as is season-end retention (the daily archive plus the outage alert and
shutdown). Next up is M5 (X notifier) and the rest of M7 (analysis).

| Milestone | Status | What it covers |
|---|---|---|
| [M1 – Restructure & dev loop](https://github.com/mwinn53/cpscoreboard/milestone/6) | ✅ Done ([#1](https://github.com/mwinn53/cpscoreboard/pull/1)) | Legacy code moved, scraper ported with tests, dev container, capture/replay |
| [M2 – Infra & pipeline](https://github.com/mwinn53/cpscoreboard/milestone/7) | ✅ Done ([#1](https://github.com/mwinn53/cpscoreboard/pull/1), [#3](https://github.com/mwinn53/cpscoreboard/pull/3)) | Terraform on EC2, GitHub Actions → ECR → SSM deploy, Caddy TLS |
| [M3a – Persistence & live updates](https://github.com/mwinn53/cpscoreboard/milestone/8) | ✅ Done ([#2](https://github.com/mwinn53/cpscoreboard/pull/2)) | SQLite change-only snapshots, restore on restart, SSE, change indicators |
| [M4 – Registration & approval](https://github.com/mwinn53/cpscoreboard/milestone/1) | ✅ Live ([#27](https://github.com/mwinn53/cpscoreboard/pull/27), [#31](https://github.com/mwinn53/cpscoreboard/pull/31), device locations [#8](https://github.com/mwinn53/cpscoreboard/issues/8)); open: DNS [#10](https://github.com/mwinn53/cpscoreboard/issues/10) | Email code → pending device → admin approval; the whole site is gated |
| [M3b – Admin settings](https://github.com/mwinn53/cpscoreboard/milestone/2) | ✅ Live ([#29](https://github.com/mwinn53/cpscoreboard/pull/29), [#30](https://github.com/mwinn53/cpscoreboard/pull/30), [#32](https://github.com/mwinn53/cpscoreboard/pull/32)); open: Alembic [#16](https://github.com/mwinn53/cpscoreboard/issues/16) | Watchlist, district schools, collection filter, logos and legacy import on `/admin/board` |
| [M5 – X notifier](https://github.com/mwinn53/cpscoreboard/milestone/3) | ✅ Built ([#17](https://github.com/mwinn53/cpscoreboard/issues/17)); dry run until X keys are saved | Posts about watched teams to X (or the log), set up on `/admin/config` |
| [M6 – History charts](https://github.com/mwinn53/cpscoreboard/milestone/4) | ✅ Live ([#40](https://github.com/mwinn53/cpscoreboard/pull/40), per-image detail [#19](https://github.com/mwinn53/cpscoreboard/issues/19)) | `/teams/{team}`: score, national and state place over time, one round at a time; per-image scores for watched teams |
| [M7 – Analysis](https://github.com/mwinn53/cpscoreboard/milestone/5) | 🚧 Season-end retention live: archive ([#34](https://github.com/mwinn53/cpscoreboard/pull/34)), outage alert and shutdown ([#39](https://github.com/mwinn53/cpscoreboard/pull/39)); Analysis tab: round samples, legacy import and a first round report (#21, in progress) | Analysis for coaches; season-end data retention |

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
| `app/posting.py`, `app/secret_box.py` | Posting about watched teams: planner, limits, X client (OAuth 1.0a), encrypted keys |
| `app/admin_config.py` | Configuration page: competition start, per-image detail status, posting to X |
| `app/board_config.py`, `app/admin_board.py` | Watchlist, district schools, collection filter and view defaults (database + admin page), legacy import |
| `app/branding.py` | Header logos, uploaded and cropped on the admin page, stored in the database |
| `app/team_detail.py` | Per-image detail: stored for watched teams while they play; fetched on demand (images and the 5-minute image chart) for any team's page |
| `app/schema.py`, `app/migrations/` | Alembic migrations, run at startup |
| `app/scoreboard_url.py` | The scoreboard address set on `/admin/config`: test fetch, and switching every live fetcher |
| `app/analysis_store.py`, `app/analysis_sampler.py`, `app/analysis_legacy.py` | Round samples for the Analysis tab: storage, the quiet-scoring sampler, the legacy CSV import |
| `app/analysis.py`, `app/analysis_web.py` | Round statistics and findings; the Analysis tab (coaches and admins) |
| `app/geo.py` | Approximate device locations from DB-IP's free city database, downloaded monthly and read offline |
| `app/team_view.py`, `app/charts.py` | Team page and the scoreboard's expandable sparkline rows; server-rendered SVG charts |
| `app/archive.py`, `app/admin_archive.py` | Season archive: the full raw scoreboard, one file per day, and its admin page |
| `app/mail.py` | Email via SES (prod), SMTP/Mailpit (dev container), or the console log |
| `app/main.py`, `app/config.py` | App factory; settings from environment variables |
| `tests/fixtures/` | Real scoreboard responses from season 17 (2024) and season 19 (2026) |
| `legacy/` | The original X-posting bot, kept for reference and the M3b/M5 ports |

### Endpoints

| Path | Returns |
|---|---|
| `/` | Dashboard: the live board with National (division), State (within division) and District places; opens on the collected division and state |
| `/teams/{team}` | A team's history, one round at a time: **Placement** (District, State, National) and **Scoring** (total score, per-image table and image-score chart), plus a table |
| `/partials/spark/{team}` | The scoreboard's expanded row for a team: this round's sparklines |
| `/events` | Server-sent events; a `board` event whenever the scoreboard changes |
| `/api/status` | Poller, source, filter and database status |
| `/api/scores` | The current collected board as JSON |
| `/api/teams/{team}/history` | A team's stored snapshots, oldest first (`?limit=`, default 1000) |
| `/api/teams/{team}/images` | A watched team's latest per-image rows and their stored history |
| `/register`, `/verify`, `/pending` | Registration: email → code → waiting for approval (public) |
| `/admin`, `/admin/claim` | Device approval (admin only); claiming admin with the bootstrap token |
| `/admin/board` | Board settings (admin only): default view, watchlist, district schools, collection filter, bulk import, logos |
| `/analysis` | Analysis (coaches and admins): round samples by division, sampling status and "sample now", settings and legacy import (admin) |
| `/analysis/rounds/{id}` | A round's report: findings, participation, our teams, images, state table, coaches' notes |
| `/admin/config` | Configuration (admin only): scoreboard address, competition start, per-image detail status, posting to X and its keys; an (i) help bubble on each section |
| `/admin/archive` | Season archive (admin only): one full scoreboard per day, downloadable |
| `/admin/server` | Snapshot and shut down the server (admin only; exists only while the outage alert's criteria are met) |
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
- **Watched teams** are pinned under their own heading (default "Watchlist"), without the
  School column; the main table still shows their school.
- **Trends:** the ▸ next to a team opens a row with this round's sparklines (total score,
  District, State, National); open rows stay open through auto-refreshes.
- **Team history:** each team number links to `/teams/{team}`. Placement charts follow the
  scoreboard's order (District, State, National); the District chart appears for district
  schools' and watched teams. Scoring shows the total score and, like the official team page,
  the per-image table and one chart of every image's score: live from the public scoreboard
  for the current round (any team), or from stored detail for watched teams.
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
| `SCOREBOARD_URL` | the public `scores.php` API | Default address; an admin can change it on `/admin/config` (tested before it's saved, applied without a restart) |
| `POLL_INTERVAL` | `60` | Seconds between polls |
| `SITE_TITLE` | `EMS CyberPatriot Next Generation Scorebot` | Header, browser tab, and email subjects/sender name |
| `DISPLAY_TIMEZONE` | `America/New_York` | Times on the site; the database stays in UTC |
| `DATA_DIR` | `data` (`/data` in the image) | Where the SQLite database lives |
| `DATABASE_URL` | — | Override the database. The default is `sqlite:///<DATA_DIR>/cpscoreboard.db`; in replay mode it's an in-memory database, so replays never mix into real history |
| `DETAIL_INTERVAL` | `300` | Seconds between per-image fetches for watched teams that are playing |
| `DETAIL_ENABLED` | `true` | Fetch per-image detail for watched teams (replay serves it from `<capture set>/images/` if present) |
| `GEOIP_ENABLED` | `true` | Approximate device locations on `/admin` (DB-IP city database, monthly download); off in replay |
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
4. **`/admin`**: approve, deny or revoke, label, delete, make a person a **coach**
   (by email: every device registered with it), or make another device an admin.
   Coaches and admins see the **Analysis** tab. Each device shows its browser and IP when registered and when last seen,
   with an approximate location (city, region, country), and is flagged if the browser
   has changed. The approval email includes the location too. Locations come from
   DB-IP's free city database, downloaded monthly to `<DATA_DIR>/geoip/` (about
   120 MB) and read locally, so no viewer's IP goes to a third party. Revoking takes effect on the next
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
| `SECRETS_KEY` | — | Fernet key that encrypts the X keys saved on `/admin/config` (SSM SecureString in production) |
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

For **watched** teams, the app also fetches the scoreboard's per-image detail
(`/api/image/scores.php?team=…`) every `DETAIL_INTERVAL` seconds while the team's
play time is moving, and writes an `image_snapshots` row per image whose score,
found/remaining counts, penalties or warnings changed. Time on the image alone
doesn't trigger a row.

The schema is managed by **Alembic** (`app/schema.py`, `app/migrations/`): the app
upgrades the database to the latest revision at startup. A database from before
Alembic is brought up to the baseline and stamped the first time it starts. To change
the schema, edit the table definition, then run
`alembic revision --autogenerate -m "what changed"` from the repo root, review the
generated file (SQLite ALTERs use batch mode), and commit it.

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
which is recorded automatically the first time a board shows play time (correct it
under **Competition start** on `/admin/config`). "Unavailable" means no usable board: a fetch error, an unexpected
response or an empty board.

`/admin/server` exists only while those criteria are met (otherwise it's a 404 and
isn't in the admin nav); if the scoreboard comes back, it disappears again.
**Snapshot and shut down** there (type `SHUT DOWN` to confirm) takes a
final EBS snapshot of `/data` and then stops the EC2 instance. Stopping is
reversible: `aws ec2 start-instances --instance-ids <id>`. The instance role may only
snapshot its own data volume and stop its own instance (`infra/iam.tf`). Terraform
supplies `PUBLIC_URL`, `AWS_INSTANCE_ID` and `DATA_VOLUME_ID`.

**Next season: the startup listener.** While the server is stopped, a small Lambda
(`infra/lambda/startup_listener.py`, `infra/startup_listener.tf`) runs once a day at
14:00 UTC:

- If the server isn't stopped, there's nothing to watch.
- If it's stopped and the public scoreboard is back (a readable board with teams), it
  emails `ADMIN_NOTIFY_EMAIL` once, with a link.
- The link opens a confirmation page, and its **Start the server** button starts the
  instance. A GET never starts anything, because mail scanners open links. Links are
  HMAC-signed and expire after 7 days; the signing key is generated on first use and kept
  in SSM (`/cpscoreboard/startup-listener/`).
- The Lambda may only start this instance.
- The site's address doesn't change: the instance has an Elastic IP, so DNS stays correct
  across stop and start.
- Cost is about $0 (free-tier Lambda and Scheduler).

### Posting to X

Set up on `/admin/config`. The app posts about **watched** teams as the legacy bot
did:

- when a team appears on the board;
- **live changes** to its score and places while it's actively playing, from 4 hours
  in (a slider, 0 to 6);
- "less than one hour remaining" and "time is up";
- once the team is **done** (time up, or play time stopped for 20 minutes),
  **periodic place changes** as other teams finish: at most every 30 minutes
  (adjustable), and only when a place moved.

Each kind can be turned off. The first board after a restart only primes the state,
so nothing is repeated.

- **Posting enabled:** a checkbox that turns all posting on or off.
- **Send to:** Dry run (the default: posts are logged on the page but not sent) or X.
- **Limits:** posts per hour and per day (X's free tier allows about 500 a month).
  Posts over a limit are skipped and logged. An optional footer (e.g. hashtags) is
  added to each post.
- **Keys:** the four OAuth 1.0 keys from the X Developer Console (Consumer Key and Secret, Access Token and Secret) for the
  posting account (the app needs Read and write permission). They're encrypted with
  `SECRETS_KEY` before they're stored and never shown again. Without `SECRETS_KEY`,
  keys can't be saved.
- **Test post:** sends one post in the current mode, ignoring the limits.

### Analysis tab

For coaches and admins (`/analysis`), modeled on the legacy R report
(`legacy/cpdataanalysis/shiny`), and built to compare in a round, across rounds and
across seasons.

- **Round samples.** A round is analyzed from a frozen sample of every team in a
  division: its final row (score, challenge scores such as Cisco, places, play time),
  per-image results, and the scoreboard's 5-minute score history. The sampler takes
  one once no score has changed for 24 hours (adjustable; usually about 72 hours after
  the round starts), for the divisions chosen in the settings (Middle School by default).
  It sends three gentle requests per team. **Sample now** does it on demand. Season and round come
  from image names (`…_cp19_…_r2_…` = CP-19 Round 2), and coaches can rename rounds.
- **Groups:** national (the division), the state (the board's default state), the
  district (district schools plus ours) and our teams (the watchlist).
- **Report:** findings written from the numbers, participation, our teams per image
  (found, completion, score), image summaries, the state table (gaps to the team above
  and to the leader), and coaches' notes saved with the round.
- **Legacy import** (admin): upload the old CSVs (CP-XI to CP-XIV). Score files become
  rounds, and timeline files become their 5-minute histories. In the old files, other
  district schools are labeled with their abbreviation (`GTMS`…) and our teams with
  their team names. Malformed rows are skipped, and a file whose name and images
  disagree (e.g. a "State Round" file holding Round 2's images) is refused.

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
polls aren't saved. Per-image detail for watched teams goes to
`captures/<session>/images/<team>/`, and replay serves the newest file per team.
`captures/` is gitignored; copy any sets you want to keep
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
