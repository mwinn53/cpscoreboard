# TODO

## Web app rewrite

- [x] **M1 – Restructure & dev loop**: move current code to `legacy/`, port scraper with tests, dev container with `capture`/`replay` modes + Mailpit, stub dashboard
  - [ ] Build the dev container and the prod image once Docker is installed (not yet verified locally)
  - [ ] Team detail pages (legacy `getteamtable`): find the per-team API endpoint and add it to capture
- [x] **M2 – Infra & pipeline**: Terraform (EC2 t4g.small, Elastic IP, EBS + snapshots, ECR, IAM/OIDC, SSM params) in us-east-1; GitHub Actions test → build → ECR → SSM deploy; Caddy TLS on sslip.io hostname
  - [ ] First `terraform apply` + `gh variable set` (user, needs AWS credentials) and first live deploy — not yet run
  - [ ] SES identity + instance `ses:SendEmail` permission → moved to M4 (request SES production access early)
  - [ ] Optional: move Terraform state to S3
- [ ] **M3 – Dashboard & live team settings**: change-only snapshots of the teams passing `COLLECT_LOCATIONS`/`COLLECT_DIVISIONS` (filter already in M1; places ranked on the full board), consider making the filter editable in admin settings, SSE push instead of 15 s htmx polling, replace `WATCH_TEAMS` env var, watchlist with places/deltas, admin settings page (reread each cycle), import `runs/team` + `runs/lookups`
- [ ] **M4 – Registration & approval**: email code → pending device → admin approve/revoke; signed device cookie; UA/IP/geo recorded; admin bootstrap token; SES in prod
- [ ] **M5 – X notifier**: port `tweet()` behind notifier interface (dry-run in dev)
- [ ] **M6 – History charts**: per-team score/place over time

## Later

- [ ] **M7 – Analysis feature** (after the initial scoreboard is built)
  - User has additional legacy analysis code to provide — get it before starting
  - **Data retention is time-sensitive:** the public scoreboard is taken down after the season. Prod must keep the latest/final scoreboard data before that happens:
    - Ensure prod snapshots in the DB are retained, not pruned (prod still doesn't archive raw pages)
    - Add an export/archive of the collected teams (scope set by the collection filter) that's kept with the EBS snapshots; confirm the filter covers what the analysis needs
    - Find out when the scoreboard is typically taken down and capture a final dataset beforehand
