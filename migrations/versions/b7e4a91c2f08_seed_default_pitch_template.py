"""Seed default Site Built Preview pitch template

Revision ID: b7e4a91c2f08
Revises: 03e7ed406604
Create Date: 2026-09-02 01:55:00.000000

Idempotent: skips insert when a pitch_templates row with this exact name
already exists (e.g. manually inserted in Supabase).
"""
from alembic import op
import sqlalchemy as sa
import uuid


# revision identifiers, used by Alembic.
revision = "b7e4a91c2f08"
down_revision = "03e7ed406604"
branch_labels = None
depends_on = None

TEMPLATE_NAME = "Site Built Preview — $29/mo"
TEMPLATE_BODY = (
    "Hey! I came across your business and noticed you don't have a website, "
    "so I built you a website preview so you could see what it could look like.\n"
    "\n"
    "It’s fully customizable, and if you want to use it, it’s just $29/month "
    "with no contracts or upfront build fee. Free Domain included or we can "
    "use the one you own.  {{demo_url}} If you’re interested, shoot me a "
    "message and I can get everything set up for you."
)


def upgrade():
    conn = op.get_bind()
    pitch_templates = sa.table(
        "pitch_templates",
        sa.column("id", sa.String),
        sa.column("name", sa.String),
        sa.column("body", sa.Text),
        sa.column("category", sa.String),
        sa.column("is_active", sa.Boolean),
    )
    existing = conn.execute(
        sa.select(pitch_templates.c.id).where(
            pitch_templates.c.name == TEMPLATE_NAME
        )
    ).fetchone()
    if existing is None:
        conn.execute(
            pitch_templates.insert().values(
                id=str(uuid.uuid4()),
                name=TEMPLATE_NAME,
                body=TEMPLATE_BODY,
                category="initial",
                is_active=True,
            )
        )


def downgrade():
    conn = op.get_bind()
    pitch_templates = sa.table(
        "pitch_templates",
        sa.column("name", sa.String),
    )
    conn.execute(
        pitch_templates.delete().where(pitch_templates.c.name == TEMPLATE_NAME)
    )
