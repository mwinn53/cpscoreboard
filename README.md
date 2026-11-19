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
shutdown), M5 (posting to X) and the Analysis tab. Next up is the rest of M7 (analysis).

| Milestone | Status | What it covers |
|---|---|---|
| [M1 – Restructure & dev loop](https://github.com/mwinn53/cpscoreboard/milestone/6) | ✅ Done ([#1](https://github.com/mwinn53/cpscoreboard/pull/1)) | Legacy code moved, scraper ported with tests, dev container, capture/replay |
| [M2 – Infra & pipeline](https://github.com/mwinn53/cpscoreboard/milestone/7) | ✅ Done ([#1](https://github.com/mwinn53/cpscoreboard/pull/1), [#3](https://github.com/mwinn53/cpscoreboard/pull/3)) | Terraform on EC2, GitHub Actions → ECR → SSM deploy, Caddy TLS |
| [M3a – Persistence & live updates](https://github.com/mwinn53/cpscoreboard/milestone/8) | ✅ Done ([#2](https://github.com/mwinn53/cpscoreboard/pull/2)) | SQLite change-only snapshots, restore on restart, SSE, change indicators |
| [M4 – Registration & approval](https://github.com/mwinn53/cpscoreboard/milestone/1) | ✅ Live ([#27](https://github.com/mwinn53/cpscoreboard/pull/27), [#31](https://github.com/mwinn53/cpscoreboard/pull/31), device locations [#8](https://github.com/mwinn53/cpscoreboard/issues/8)); open: DNS [#10](https://github.com/mwinn53/cpscoreboard/issues/10) | Email code → pending device → admin approval; the whole site is gated |
| [M3b – Admin settings](https://github.com/mwinn53/cpscoreboard/milestone/2) | ✅ Live ([#29](https://github.com/mwinn53/cpscoreboard/pull/29), [#30](https://github.com/mwinn53/cpscoreboard/pull/30), [#32](https://github.com/mwinn53/cpscoreboard/pull/32)); open: Alembic [#16](https://github.com/mwinn53/cpscoreboard/issues/16) | Watchlist, district schools, collection filter, logos and legacy import on `/admin/board` |
| [M5 – X notifier](https://github.com/mwinn53/cpscoreboard/milestone/3) | ✅ Built ([#17](https://github.com/mwinn53/cpscoreboard/issues/17)); dry run until X keys are saved | Posts about watched teams to X (or the log), set up on `/admin/config` |
| [M6 – History charts](https://github.com/mwinn53/cpscoreboard/milestone/4) | ✅ Live ([#40](https://github.com/mwinn53/cpscoreboard/pull/40), per-image detail [#19](https://github.com/mwinn53/cpscoreboard/issues/19)) | `/teams/{team}`: score, national and state place over time, one round at a time; per-image scores for watched teams |
| [M7 – Analysis](https://github.com/mwinn53/cpscoreboard/milestone/5) | 🚧 Season-end retention live: archive ([#34](https://github.com/mwinn53/cpscoreboard/pull/34)), outage alert and shutdown ([#39](https://github.com/mwinn53/cpscoreboard/pull/39)); Analysis tab ([#58](https://github.com/mwinn53/cpscoreboard/pull/58)): data sets, legacy import, reports with charts and written narrative, season and round comparisons, trickle collection ([#60](https://github.com/mwinn53/cpscoreboard/pull/60); collect after 3¾ hours played and 60 minutes idle or 4 hours idle, Collect all, Cisco Quiz and Packet Tracer, [#61](https://github.com/mwinn53/cpscoreboard/pull/61)) | Analysis for coaches; season-end data retention |
| [M8 – Season operations & admin polish](https://github.com/mwinn53/cpscoreboard/milestone/9) | 🚧 In progress. Next: archive copy to S3 ([#71](https://github.com/mwinn53/cpscoreboard/issues/71)) in [#97](https://github.com/mwinn53/cpscoreboard/pull/97). Planned: messaging alternative to X ([#53](https://github.com/mwinn53/cpscoreboard/issues/53)), mobile layout ([#70](https://github.com/mwinn53/cpscoreboard/issues/70), parked), X standings images ([#72](https://github.com/mwinn53/cpscoreboard/issues/72)) | Running the season smoothly |
| [M9 – Analysis evaluation & enhancements](https://github.com/mwinn53/cpscoreboard/milestone/10) | 🚧 In progress. Done: where the points went (points within reach [#76](https://github.com/mwinn53/cpscoreboard/issues/76), strengths and weaknesses [#75](https://github.com/mwinn53/cpscoreboard/issues/75), penalties [#78](https://github.com/mwinn53/cpscoreboard/issues/78)) in [#92](https://github.com/mwinn53/cpscoreboard/pull/92); the R-report evaluation ([#66](https://github.com/mwinn53/cpscoreboard/issues/66)) became the rigor work in [#81](https://github.com/mwinn53/cpscoreboard/issues/81); pace against the top quarter ([#77](https://github.com/mwinn53/cpscoreboard/issues/77)) in [#93](https://github.com/mwinn53/cpscoreboard/pull/93); what it takes to advance, Middle School ([#68](https://github.com/mwinn53/cpscoreboard/issues/68)) in [#94](https://github.com/mwinn53/cpscoreboard/pull/94). interactive charts ([#65](https://github.com/mwinn53/cpscoreboard/issues/65)) in [#95](https://github.com/mwinn53/cpscoreboard/pull/95). Next: coach-chosen comparisons ([#67](https://github.com/mwinn53/cpscoreboard/issues/67)) in [#96](https://github.com/mwinn53/cpscoreboard/pull/96). Planned: AI-written narratives with a cost estimate first ([#64](https://github.com/mwinn53/cpscoreboard/issues/64)), export ([#69](https://github.com/mwinn53/cpscoreboard/issues/69)), image order ([#79](https://github.com/mwinn53/cpscoreboard/issues/79)), what drives the score ([#80](https://github.com/mwinn53/cpscoreboard/issues/80)) | Make the analysis more useful to coaches |

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
| `app/static_files.py`, `app/static/` | Stylesheet and scripts (htmx 2.0.4 is served from here, not a CDN); pages link them with a content hash (`?v=…`), and those URLs are cached for a year |
| `app/auth.py`, `app/devices.py` | Registration (email code), device approval, admin page, access checks |
| `app/posting.py`, `app/secret_box.py` | Posting about watched teams: planner, limits, X client (OAuth 1.0a), encrypted keys |
| `app/admin_config.py` | Configuration page: competition start, per-image detail status, posting to X |
| `app/board_config.py`, `app/admin_board.py` | Watchlist, district schools, collection filter and view defaults (database + admin page), legacy import |
| `app/branding.py` | Header logos, uploaded and cropped on the admin page, stored in the database |
| `app/team_detail.py` | Per-image detail: stored for watched teams while they play; fetched on demand (images and the 5-minute image chart) for any team's page |
| `app/schema.py`, `app/migrations/` | Alembic migrations, run at startup |
| `app/scoreboard_url.py` | The scoreboard address set on `/admin/config`: test fetch, and switching every live fetcher |
| `app/analysis_store.py`, `app/analysis_collector.py`, `app/analysis_legacy.py` | Data sets for the Analysis tab: storage, the team-at-a-time collector, the legacy CSV import |
| `app/analysis.py`, `app/analysis_narrative.py`, `app/analysis_charts.py` | A round's statistics, its written narrative and its SVG charts |
| `app/analysis_stats.py` | Rank-based tests (exact p-values for small samples), BCa bootstrap intervals, rank correlations and the Holm correction, on SciPy |
| `app/analysis_focus.py` | Where the points went: points within reach, strengths and weaknesses by image, penalties |
| `app/analysis_advance.py` | What it takes to advance (Middle School, CP-19 rules): the State Round projection after the Introductory Round, the combined line after the State Round, the National Finals line after the Semifinal |
| `app/analysis_pace.py` | Pace against the top quarter: where in the round our teams fall behind, and slow starts per image |
| `app/analysis_compare.py`, `app/analysis_web.py` | Season and round comparisons; the Analysis tab (coaches and admins) |
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
| `/analysis` | Analysis (coaches and admins): reports by division and season, collection progress (refreshed every 30 s), the throttle, Collect all and divisions to collect (admin), legacy import (admin), compare two reports |
| `/analysis/reports/{id}` | A round's report: in brief, narrative, charts, our teams, images, what it takes to advance, in-round progress and pace against the top quarter, top teams, the state table, the comparisons, coaches' notes (`/analysis/rounds/{id}` redirects here). `?state=TX` reads it for another state |
| `/analysis/reports/{id}/charts/{name}?lo=&hi=` | One chart redrawn for an x range (the zoom on the progress chart and the score and play-time distributions) |
| `/analysis/seasons`, `/analysis/seasons/{season}` | Season over season (participation, percentiles, image families); one season's rounds, with the teams we follow |
| `POST /analysis/choices` | Save a division's comparisons (any coach): teams to follow, another state, the top N |
| `/analysis/compare?a=&b=` | Any two reports side by side (e.g. preliminary against final, or two rounds) |
| `/admin/config` | Configuration (admin only): scoreboard address and update interval (fixed or variable), competition start, posting to X and its keys; an (i) help bubble on each section |
| `/admin/archive` | Season archive (admin only): one full scoreboard per day, downloadable, and which days are copied to S3 |
| `/admin/server` | Snapshot and shut down the server (admin only; exists only while the outage alert's criteria are met) |
| `/brand/left`, `/brand/right` | Header logos (public); placeholders until uploaded on `/admin/board` |
| `/healthz` | Public health check for Docker and the deploy; returns only `{"status": "ok"}` |
| `/api/docs` | Interactive API docs (dev only) |

Everything except `/healthz`, the registration pages and `/static` requires an
approved device (see [Access control](#access-control)).

### The dashboard

- **Filters** in the header: search, division, state and rows. The page opens on the
  default view set on `/admin/board`, and the address bar follows the filters, so a
  reload or a shared link keeps the view. With every division in every state (thousands
  of teams), the board shows the top 100 rows unless you pick "All rows".
- **Columns:** School, score first, then a **Placement** group in the order:
  - **District**: place among the district schools' teams plus the watched teams, within the division.
  - **State**: place in the state, within the division.
  - **National**: place in the division, nationally.

  Each Placement header shows how many teams it ranks, e.g. **District (16)**, **State (22)**,
  **National (205)**. A count appears only when every team in the table shares one division
  (and, for State, one state); with the filter on All there's no single total.
  State, Division and Tier columns appear only when the filter is set to All.
- **Total Score:** one column: the official total (images, Cisco and any adjustment)
  once it's published, otherwise the image score.
- **Flags:** the official warning codes, plus a blue **C** when a team has scored Cisco
  points (quiz or Packet Tracer); the key under the table explains each.
- **Trends:** ▲▼ for place and +/− for score since the last change, in fixed slots so
  numbers line up.
- **Watched teams** are pinned under their own heading (default "Watchlist"), without the
  School column; the main table still shows their school.
- **Trends:** the ▸ next to a team opens a row with this round's sparklines (total score,
  District, State, National); open rows stay open through auto-refreshes. The watched
  teams' rows open by default; one you close stays closed.
- **Team history:** each team number links to `/teams/{team}`. Placement charts follow the
  scoreboard's order (District, State, National); the District chart appears for district
  schools' and watched teams. Scoring shows the total score and, like the official team page,
  the per-image table (with Cisco Quiz and Cisco Packet Tracer rows for the current round)
  and one chart of every image's score: live from the public scoreboard for the current
  round (any team), or from stored detail for watched teams. Once the Analysis collector
  has stored a team and its score hasn't changed since, the page uses that copy instead
  of asking the public scoreboard again.
- **Polling:** each check downloads the whole public scoreboard (about 750 KB; it isn't
  compressed and can't be asked "has anything changed?"). With the variable interval on
  (/admin/config), the wait doubles after 3 checks without a change, up to 10 minutes, and
  up to 30 minutes after 6 hours without a change (between rounds); the first change
  resets it. **Reset to 60 seconds and check now** on /admin/config snaps it back by hand (e.g.
  just before a round starts).
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
| `POLL_INTERVAL` | `60` | Seconds between polls, until the admin sets the update interval on /admin/config |
| `SITE_TITLE` | `EMS CyberPatriot Next Generation Scorebot` | Header, browser tab, and email subjects/sender name |
| `DISPLAY_TIMEZONE` | `America/New_York` | Times on the site; the database stays in UTC |
| `DATA_DIR` | `data` (`/data` in the image) | Where the SQLite database lives |
| `DATABASE_URL` | — | Override the database. The default is `sqlite:///<DATA_DIR>/cpscoreboard.db`; in replay mode it's an in-memory database, so replays never mix into real history |
| `DETAIL_INTERVAL` | `300` | Seconds between per-image fetches for watched teams that are playing |
| `DETAIL_ENABLED` | `true` | Fetch per-image detail for watched teams (replay serves it from `<capture set>/images/` if present) |
| `GEOIP_ENABLED` | `true` | Approximate device locations on `/admin` (DB-IP city database, monthly download); off in replay |
| `ARCHIVE_ENABLED` | `true` | Save the full scoreboard once per day (see [Season archive](#season-archive)); always off in replay |
| `ARCHIVE_BUCKET` | | Also copy the archive to this S3 bucket (set by Terraform in prod; blank = off) |
| `ARCHIVE_SYNC_MINUTES` | `60` | How often the S3 copy is checked |
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
whose score, images, warnings, score time, or place in its division or its state's
division changed. Play time alone doesn't trigger a row, and neither do the overall
and statewide all-division places, which shift whenever any team anywhere scores
(they caused 76% of the rows until #82). The scoreboard's trend rows are built once
per board change and shared by every viewer. On restart, the dashboard reloads the
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

With `ARCHIVE_BUCKET` set (Terraform sets it in prod, `infra/archive.tf`), the files
are also copied to S3 under `archive/`: at startup and then every hour, a file the
bucket doesn't have is uploaded, and a day's older file is deleted once its
replacement is there, so the bucket mirrors the folder (`aws s3 sync
s3://<bucket>/archive/ <folder>` gives a folder that replays). The bucket is private,
encrypted and versioned. Replaced versions are kept for 30 days, and files move to
Glacier 180 days after upload, which is after the season. `/admin/archive` shows which
days are in S3, when the copy last ran and any error.

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
- **Round length:** CP-19 rounds are 4 hours, so "an hour left" posts at 3:00 and "time is
  up" at 4:00; the live-changes slider runs up to 4 hours.
- **Out of credits:** when X answers 402 (API credits used up), real posts are skipped
  (and logged) rather than failing one by one, and /admin/config says so. After adding
  credits, a test post that goes through resumes posting.

### Analysis tab

For coaches and admins (`/analysis`), modeled on the legacy R report
(`legacy/cpdataanalysis/shiny`), and built to compare in a round, across rounds and
across seasons.

- **Data sets.** Each report is built from a data set: every team in a division, with
  its final row (score, challenge scores such as Cisco, places, play time), per-image
  results and the scoreboard's 5-minute score history.
- **Collection, a team at a time.** For the divisions chosen on the Analysis page
  (Middle School by default), a team is collected once it has surely finished: at
  least 3¾ hours of play time and idle for 60 minutes, or idle for 4 hours whatever it
  played. Reports are written after the round, so waiting costs nothing and few teams
  are fetched twice. Each team is two requests (its per-image table and 5-minute image
  history); the Cisco scores and total come from the board feed. **Collect all** (admin) fetches the division's remaining teams now,
  finished or not, at the same throttle and pace; teams still playing are fetched
  again when their score changes. A short pause follows each team. Teams finish across the weekend, so it's a trickle. **Teams fetched at
  once** (a slider, default 1; 0 pauses) is the throttle. The page shows how many
  teams' data sets are complete, how many are waiting, how many are still playing and
  an ETA. A team is fetched again only if its score changes later; places keep moving
  while others play, so collected teams' places are refreshed from the board without
  fetching. The season comes from image names (`…_cp19_…`). The round can't be trusted from
  them (CP-19 Round 1 used `…_intro_r2_…` images), so the admin sets **Round being collected**
  on the Analysis page; setting it also moves the data set being filled. A report's round
  can be corrected with its name and notes.
- **Run report:** once every team that played is collected (100%), the Analysis page
  shows a **Run report** button and a countdown; the report runs itself 24 hours after the
  data set first reached 100%. Running makes the data set final: nothing more is collected
  into it and places stop updating (an admin can **Reopen** it from the report). Reports
  are marked collecting, complete (with the run time) or report run.
- **Groups:** national (the division), the state (the board's default state), the
  district (district schools plus ours) and our teams (the watchlist).
- **Report:** "In brief" conclusions, then sections that each pair a narrative with
  charts. The narrative is written from the numbers, using the R report's hand-written
  paragraphs as templates, so a statement only appears when the data supports it.
  Charts are server-rendered SVG with hover tips and a table view:
  - score by state (box plots, the state highlighted, the national median);
  - where teams landed nationally and in the state (our teams, district teams and
    other state teams marked);
  - score and play-time distributions, and score against play time;
  - teams per state against the state median (correlation);
  - score by images attempted, completion per image, and items found per image;
  - in-round progress: our teams' score by time since each team started, against
    the field's median and middle half, and the top quarter's.
- **Interactive charts** (a small script over the server's SVG; without it the charts
  and tables are unchanged):
  - **highlight a team:** click its dot, line or table row, or type its number in
    "Highlight a team", and it stands out in every chart and table (click again or
    press Esc to clear);
  - **read for another state:** "Read for" redraws the report with that state as the
    blue highlight and in the state comparisons and tables; our teams stay orange;
  - **toggles:** the team-group legend entries show or hide those dots on the whole
    page; the progress and advancement legends show or hide their series; on the
    season and comparison pages, a line's label shows or hides it;
  - **zoom:** drag across the progress chart or the score and play-time distributions
    (or use "Zoom to…") and the server redraws that range with its own ticks and bins;
    "Reset zoom" goes back.
- **Comparisons** (chosen by the coaches, saved per division for every coach):
  - **teams to follow** (rivals, last year's finalists): a ring on their dots in every
    chart, a ★ in every table, and their own table on each report;
  - **another state** and **the top N teams nationally** (off, 10, 25, 50 or 100):
    a chart and a table of the groups (nation, our state, that state, the top N, the
    teams we follow, our teams), each tested against our state;
  - the season page draws the followed teams' percentile by round, with the chosen
    state's median team beside ours.
- **What it takes to advance** (Middle School reports from CP-18 on). From the CP-19
  Rules Book: the top 60% on the Introductory Round and State Round scores combined go
  to the Semifinals, and the three highest Semifinal scores go to the National Finals,
  one team per school (our teams share one, so the report says only the best of them
  can go). From the CP-18 Rules Book (section 4004), not yet checked for CP-19: ties at
  the line all advance, and the top three in each state on the combined score win AFA
  State Awards.
  - **After the Introductory Round, a projection:** for each of our teams, the State Round
    points it would need for the Semifinals and for a top-3 state award (the median and
    the middle 80% of 2,000 simulated State Rounds) and its chance at its projected pace.
    The simulation keeps each team's Introductory Round rank, shuffled as much as past
    seasons' State Rounds shuffled the round before (Spearman correlation), on the scale
    and with the share of returning teams those seasons showed. With no past season that
    has both rounds, it assumes the same scale, a correlation of 0.6 and every team
    returning, and says so: import past seasons to improve it. A chart and a table show
    the ranges; "Hide the projection" turns them off (remembered in the browser).
  - **With the State Round:** the exact combined line, each team's margin, its place in
    the state and the gap to a state award.
  - **With the Semifinal:** the third-highest score (the National Finals line) and each
    team's margin. Other schools' duplicate teams aren't removed (the data can't see
    schools).
- **Pace against the top quarter** (on each report with a 5-minute history). The top
  quarter is the teams with a history whose final score was at or above the field's
  upper quartile. For each of our teams: the points behind the top quarter's median at
  each hour and the hour the gap grew the most; when half or more of the final gap
  opened in the first hour, the report points at the opening checklist. Per image: our
  median minutes to the first points and to half of the final score, against the top
  quarter's (a start 15 or more minutes slower is called out). "In brief" names the hour
  where most ground was lost. Season pages don't include it yet: they skip the 5-minute
  history to load quickly.
- **Where the points went** (on each report), to guide practice. Estimates, and the
  page says so:
  - **Points within reach:** for each of our teams, the items the field's top quarter
    found on each image and we didn't, what they're worth (an image's points per item
    is the median score ÷ items found among teams with no penalties there that found
    more than we did) and the places they'd have gained in the state and nationally;
    then the points to the next place in the state and to the state's top quarter, with
    the fewest changes that cover them (dropping penalties first, then the richest
    items). "In brief" names the image with the most points within reach.
  - **Strengths and weaknesses:** each team's completion percentile on every image
    (and its Cisco percentile) against its overall percentile; differences of 20 points
    or more are marked. On the season pages, the same difference per image family
    across team-rounds, with a Wilcoxon signed-rank test per family and a Holm
    correction across the families (exploratory).
  - **Penalties:** per image, the share of our teams with a penalty against the rest of
    the field, mean penalties, Fisher's exact test and the points lost (items found ×
    points per item − score).
  Time axes, limit lines and the narrative follow the round's time limit: 4 hours
  (CP-19 on) or 6 (the legacy seasons), told apart by how long teams played.
  Plus the top N teams (10–100), the state table and coaches' notes. A report also notes
  participation against the season's previous round and the same round last season.
  Coaches can correct a team's group (ours / district / neither) in a data set from the
  report page.
  Reports are cached in memory per data set revision; after a restart the newest ones
  are computed in the background, so the first view is quick.
- **Statistical tests.** Scores are skewed, with ties and outliers, so the tests are
  rank-based and effect sizes come first:
  - the state against the rest of the division, and district teams against the rest of
    the state: the chance a team from one group outscores a team from the other (with a
    95% interval), the difference in medians with a bootstrap interval, and a
    Mann–Whitney p-value (significant below 0.05);
  - 95% bootstrap intervals (BCa) for each group's median; states with fewer than 5 teams are
    faded on the state chart (their medians are unreliable);
  - rank correlations (ρ) with p-values for teams per state and for play time;
  - on the season pages, our program across rounds: a signed-rank test of our
    team-rounds' percentiles against the median team, a trend test over the rounds
    (Kendall's τ), and the state's median team against the nation's, round by round.
  Our own 3–4 teams are too few to test within one round. SciPy computes exact p-values
  where the samples are small (most season-page tests) and the normal approximation otherwise.
- **Comparisons.** Scores aren't comparable across rounds, so comparisons use
  percentiles (the share of the division outscored) and completion by image family
  (Windows, Windows Server, Linux). Final scores are used where a round has both.
  - **Season** (`/analysis/seasons/{season}`): our teams' percentile by round, with
    participation, medians and image-family completion, and the teams we follow.
  - **Season over season** (`/analysis/seasons`): the participation grid that the old
    reports typed by hand, our best and median team, and the state's median team by
    round.
  - **Two reports** (`/analysis/compare`): any pair side by side, with our teams
    matched by number within a season.
- **Legacy import** (admin): upload the old CSVs (CP-XI to CP-XIV). Score files become
  data sets, and timeline files become their 5-minute histories. In the old files, other
  district schools are labeled with their abbreviation (`GTMS`…) and our teams with
  their team names. A file without names (CP-XI Round 1) borrows them from the same
  season's other files. Malformed rows are skipped, and a file whose name and images
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

**Tests** (`pytest -q`, under a minute). `tests/conftest.py` keeps them quick: a new test
database is created straight from the table definitions and stamped at the latest
migration (`tests/test_schema.py` still runs the real migrations), commits skip the disk
flush, each fixture scoreboard is parsed once per run, and deliberate waits (the
wrong-admin-token penalty, the collector's pause between teams and its retry delay) are
zero.

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
| `infra/` | Terraform: EC2, Elastic IP, `/data` volume and snapshots, the archive bucket, ECR, IAM/OIDC, logs, SSM settings |
| `deploy/` | Production compose file, Caddyfile, and the SSM deploy scripts |
| `.github/workflows/` | `ci.yml` (tests, plus an image build on PRs) and `deploy.yml` (master → AWS) |
