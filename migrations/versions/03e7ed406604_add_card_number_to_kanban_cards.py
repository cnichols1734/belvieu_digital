"""add card_number to kanban_cards

Revision ID: 03e7ed406604
Revises: 43f18549e52e
Create Date: 2026-02-21 22:57:06.976432

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '03e7ed406604'
down_revision = '43f18549e52e'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('kanban_cards', schema=None) as batch_op:
        batch_op.add_column(sa.Column('card_number', sa.Integer(), nullable=True))
        batch_op.create_unique_constraint('uq_kanban_cards_card_number', ['card_number'])


def downgrade():
    with op.batch_alter_table('kanban_cards', schema=None) as batch_op:
        batch_op.drop_constraint('uq_kanban_cards_card_number', type_='unique')
        batch_op.drop_column('card_number')
