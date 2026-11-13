# CyberPatriot Scoreboard

A containerized web dashboard for following teams on the public CyberPatriot
scoreboard. It polls the scoreboard API once a minute and ranks every team
overall, by division, by state, and by state within division.

The original command-line bot that posts to X lives in [legacy/](legacy/).
See [TODO.md](TODO.md) for the roadmap.

## Layout

| Path | Purpose |
|---|---|
| `app/scraper.py` | Parses `scores.php` JSON into ranked `TeamScore` rows |
| `app/sources.py` | Where data comes from: `live`, `capture` (live + save changes), `replay` |
| `app/poller.py` | Background poll loop with change detection and backoff |
| `app/web.py`, `app/templates/` | Dashboard (htmx, refreshes every 15 s), `/api/scores`, `/healthz` |
| `tests/fixtures/` | Real scoreboard responses from season 17 (2024) and season 19 (2026) |

## Configuration

All settings are environment variables; see [.env.example](.env.example).

| Variable | Default | Notes |
|---|---|---|
| `APP_ENV` | `dev` | `prod` refuses any `SCRAPE_MODE` other than `live` |
| `SCRAPE_MODE` | `live` | `live`, `capture`, or `replay` |
| `POLL_INTERVAL` | `60` | Seconds between polls |
| `CAPTURE_SET` | — | Replay: folder under `captures/`, or any folder path |
| `REPLAY_SPEED` | `1` | e.g. `20` plays an hour of captures in 3 minutes |
| `REPLAY_LOOP` | `false` | Restart the replay when it ends |
| `COLLECT_LOCATIONS` | — (all) | Comma-separated locations to keep, e.g. `VA,MD,DC` |
| `COLLECT_DIVISIONS` | — (all) | Comma-separated divisions to keep, e.g. `Open,Middle School` |
| `WATCH_TEAMS` | — | Comma-separated team numbers to pin; always collected (temporary; moves to the database in milestone 3) |

### Collection filter

`COLLECT_LOCATIONS` and `COLLECT_DIVISIONS` limit which teams the app keeps in
memory and, from milestone 3, in the database. They're case-insensitive. When
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
registration emails from milestone 4 onward.

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

| Path | Purpose |
|---|---|
| `infra/` | Terraform: EC2, Elastic IP, `/data` volume and snapshots, ECR, IAM/OIDC, logs, SSM settings |
| `deploy/` | Production compose file, Caddyfile, and the SSM deploy scripts |
| `.github/workflows/` | `ci.yml` (tests, plus an image build on PRs) and `deploy.yml` (master → AWS) |
