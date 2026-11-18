"""report run: a live data set's countdown and final state

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-17 12:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('analysis_rounds', schema=None) as batch_op:
        batch_op.add_column(sa.Column('complete_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('report_run_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('analysis_rounds', schema=None) as batch_op:
        batch_op.drop_column('report_run_at')
        batch_op.drop_column('complete_at')
