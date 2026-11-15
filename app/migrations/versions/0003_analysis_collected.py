"""analysis collected: live data sets fill a team at a time

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-15 22:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('analysis_collected',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('round_id', sa.Integer(), nullable=False),
    sa.Column('team_number', sa.String(length=32), nullable=False),
    sa.Column('score_key', sa.String(length=64), nullable=False),
    sa.Column('collected_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['round_id'], ['analysis_rounds.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('round_id', 'team_number', name='uq_analysis_collected')
    )
    with op.batch_alter_table('analysis_collected', schema=None) as batch_op:
        batch_op.create_index('ix_analysis_collected_team', ['team_number'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('analysis_collected', schema=None) as batch_op:
        batch_op.drop_index('ix_analysis_collected_team')
    op.drop_table('analysis_collected')
