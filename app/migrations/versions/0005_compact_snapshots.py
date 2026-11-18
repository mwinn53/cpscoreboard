"""compact snapshots: drop rows caused only by cross-division place changes

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-18 12:00:00

A team snapshot used to be written whenever the team's overall or statewide
all-division place moved, which happens whenever any team in any division scores.
Those places are no longer part of the change test (app/store.py ``change_key``);
this removes the existing rows that differ from the team's previous row only in
them (about 76% of the table in production). app/schema.py vacuums afterwards.
"""
from alembic import op


revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None

TRACKED = ("ccs_score", "total", "adjustment", "images", "code", "score_time", "place_division",
           "place_state_division", "location", "division", "tier")


def upgrade() -> None:
    lags = ", ".join(f"lag({c}) over w AS prev_{c}" for c in TRACKED)
    same = " AND ".join(f"{c} IS prev_{c}" for c in TRACKED)
    op.execute(f"""
        DELETE FROM team_snapshots WHERE id IN (
            SELECT id FROM (
                SELECT id, {", ".join(TRACKED)}, lag(id) over w AS prev_id, {lags}
                FROM team_snapshots
                WINDOW w AS (PARTITION BY team_number ORDER BY observed_at, id)
            ) WHERE prev_id IS NOT NULL AND {same}
        )""")


def downgrade() -> None:
    pass  # the removed rows carried nothing the app reads
