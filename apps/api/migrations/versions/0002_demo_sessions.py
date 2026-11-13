"""demo_sessions: public demo calls, for per-IP and daily spend caps

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'demo_sessions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('ip_hash', sa.String(length=64), nullable=False),
        sa.Column('room_name', sa.String(length=128), nullable=False),
        sa.Column('seconds_reserved', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_demo_sessions_ip_hash', 'demo_sessions', ['ip_hash'])
    op.create_index('ix_demo_sessions_created_at', 'demo_sessions', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_demo_sessions_created_at', table_name='demo_sessions')
    op.drop_index('ix_demo_sessions_ip_hash', table_name='demo_sessions')
    op.drop_table('demo_sessions')
