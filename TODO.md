# TODO

Order agreed 2026-11-13: M3a → M4 → M3b → M5 → M6 → M7 (admin settings need M4's admin login first).

## Web app rewrite

- [x] **M1 – Restructure & dev loop**: move current code to `legacy/`, port scraper with tests, dev container with `capture`/`replay` modes + Mailpit, stub dashboard
  - [ ] Build the dev container locally once Docker is installed (the prod image is verified by CI and the live deploy)
  - [ ] Team detail pages (legacy `getteamtable`): find the per-team API endpoint and add it to capture
- [x] **M2 – Infra & pipeline**: Terraform (EC2 t4g.small, Elastic IP, EBS + snapshots, ECR, IAM/OIDC, SSM params) in us-east-1; GitHub Actions test → build → ECR → SSM deploy; Caddy TLS on sslip.io hostname
  - [x] First `terraform apply`, repo variables, first deploy (live 2026-11-13 at https://18-204-24-39.sslip.io)
  - [ ] SES identity + instance `ses:SendEmail` permission → moved to M4 (request SES production access early)
  - [ ] Optional: move Terraform state to S3 (it's local in `infra/` now; back it up)
- [x] **M3a – Persistence & live updates**: SQLite change-only snapshots of collected teams (places ranked on the full board), restore on restart, SSE push, score/place change indicators, `/api/teams/{team}/history`
- [ ] **M4 – Registration & approval**: email code → pending device → admin approve/revoke; signed device cookie; UA/IP/geo recorded; admin bootstrap token; SES in prod; gate the dashboard
- [ ] **M3b – Admin settings** (behind M4 admin login): edit watchlist, aliases, `COLLECT_LOCATIONS`/`COLLECT_DIVISIONS` in the UI (poller rereads each cycle, replacing the env vars); import legacy `runs/team` + `runs/lookups`
- [ ] **M5 – X notifier**: port `tweet()` behind notifier interface (dry-run in dev)
- [ ] **M6 – History charts**: per-team score/place over time (data from M3a)
- [ ] Schema migrations: adopt Alembic before the first change to an existing table

## Later

- [ ] **M7 – Analysis feature** (after the initial scoreboard is built)
  - User has additional legacy analysis code to provide — get it before starting
  - **Data retention is time-sensitive:** the public scoreboard is taken down after the season. Prod must keep the latest/final scoreboard data before that happens:
    - Prod snapshots are stored from M3a on and never pruned (prod still doesn't archive raw pages)
    - Add an export/archive of the collected teams (scope set by the collection filter) that's kept with the EBS snapshots; confirm the filter covers what the analysis needs
    - Find out when the scoreboard is typically taken down and capture a final dataset beforehand
