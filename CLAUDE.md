# Working on this repo

## Every PR (do this without being asked)

1. **README.md**: update everything the change affects: the Roadmap table (status
   column, with PR links), routes, configuration variables, and behavior sections.
2. **Issues and milestones**: put `Closes #N` in the PR body for issues it finishes;
   comment on issues it only advances; open issues for follow-ups in the right
   milestone; close a milestone when its last issue closes.
3. Fill in the checklist in `.github/pull_request_template.md`.
4. **Punch list** ([#43](https://github.com/mwinn53/cpscoreboard/issues/43)): pick up
   items related to the PR's area (or one or two small ones), tick them off in the
   issue (move them under Done with the PR number), and name them in the PR body.
   Add new one-off ideas there instead of opening issues or asking about each.
5. **TODO.md** is the user's brainstorm list: file each new idea as a GitHub issue
   (label `feature-request`, right milestone, short spec), then clear it from the list.
6. If `infra/` changed, run `terraform plan` and note it in the PR; apply it before
   or with the deploy.

## Notes

- Merging to `master` deploys to production (`.github/workflows/deploy.yml`).
- Tests: `pytest -q`.
- Schema changes are Alembic revisions (`alembic revision --autogenerate -m ...`); see
  `app/schema.py`. Take an EBS snapshot of `/data` before deploying a migration that
  alters existing tables.
- Write files as UTF-8 (on Windows, Python's default encoding is cp1252).
