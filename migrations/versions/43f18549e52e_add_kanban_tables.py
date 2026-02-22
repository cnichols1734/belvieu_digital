"""add kanban tables

Revision ID: 43f18549e52e
Revises: 82f553b0f4db
Create Date: 2026-02-21 15:05:59.372600

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '43f18549e52e'
down_revision = '82f553b0f4db'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('kanban_columns',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('kanban_cards',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('kanban_column_id', sa.String(length=36), nullable=False),
    sa.Column('title', sa.String(length=500), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('labels', sa.Text(), nullable=True),
    sa.Column('comments', sa.Text(), nullable=True),
    sa.Column('prospect_id', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.ForeignKeyConstraint(['kanban_column_id'], ['kanban_columns.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['prospect_id'], ['prospects.id'], ),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('kanban_cards')
    op.drop_table('kanban_columns')
