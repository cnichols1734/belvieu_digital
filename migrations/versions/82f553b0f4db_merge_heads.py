"""merge heads

Revision ID: 82f553b0f4db
Revises: a3f8c1d92e47, add_performance_indexes
Create Date: 2026-02-21 15:05:53.599926

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '82f553b0f4db'
down_revision = ('a3f8c1d92e47', 'add_performance_indexes')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
