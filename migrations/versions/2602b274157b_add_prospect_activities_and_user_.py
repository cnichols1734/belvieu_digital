"""add prospect_activities and user password_reset fields

Revision ID: 2602b274157b
Revises: cd77260a1e5a
Create Date: 2026-02-08 23:14:19.559621

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2602b274157b'
down_revision = 'cd77260a1e5a'
branch_labels = None
depends_on = None


def upgrade():
    # --- New table: prospect_activities ---
    op.create_table('prospect_activities',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('prospect_id', sa.String(length=36), nullable=False),
        sa.Column('activity_type', sa.String(length=50), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('actor_user_id', sa.String(length=36), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['prospect_id'], ['prospects.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_prospect_activities_prospect_id', 'prospect_activities', ['prospect_id'], unique=False)

    # --- New columns on users: password reset ---
    op.add_column('users', sa.Column('password_reset_token', sa.String(length=255), nullable=True))
    op.add_column('users', sa.Column('password_reset_expires', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column('users', 'password_reset_expires')
    op.drop_column('users', 'password_reset_token')

    op.drop_index('ix_prospect_activities_prospect_id', table_name='prospect_activities')
    op.drop_table('prospect_activities')
