"""add domain choice fields to sites

Revision ID: 5523c4d8d984
Revises: 2602b274157b
Create Date: 2026-02-10 20:47:18.002811

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5523c4d8d984'
down_revision = '2602b274157b'
branch_labels = None
depends_on = None


def upgrade():
    # --- New columns on sites: domain selection (client intent) ---
    op.add_column('sites', sa.Column('domain_choice', sa.String(length=30), nullable=True))
    op.add_column('sites', sa.Column('requested_domain', sa.String(length=255), nullable=True))
    op.add_column('sites', sa.Column('requested_domain_price', sa.Float(), nullable=True))
    op.add_column('sites', sa.Column('domain_self_purchase', sa.Boolean(), server_default='0', nullable=True))
    op.add_column('sites', sa.Column('domain_choice_at', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column('sites', 'domain_choice_at')
    op.drop_column('sites', 'domain_self_purchase')
    op.drop_column('sites', 'requested_domain_price')
    op.drop_column('sites', 'requested_domain')
    op.drop_column('sites', 'domain_choice')
