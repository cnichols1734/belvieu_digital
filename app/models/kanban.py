"""Kanban board models.

Provides columns (lanes) and cards for the internal research pipeline.
Cards hold markdown research briefs and can be linked to Prospects.
"""

import uuid

from app.extensions import db


class KanbanColumn(db.Model):
    __tablename__ = "kanban_columns"

    id = db.Column(
        db.String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    title = db.Column(db.String(255), nullable=False)
    position = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(
        db.DateTime(timezone=True), server_default=db.func.now()
    )

    cards = db.relationship(
        "KanbanCard",
        backref="column",
        lazy="dynamic",
        cascade="all, delete-orphan",
        order_by="KanbanCard.position",
    )

    def __repr__(self):
        return f"<KanbanColumn {self.title}>"


class KanbanCard(db.Model):
    __tablename__ = "kanban_cards"

    id = db.Column(
        db.String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    kanban_column_id = db.Column(
        db.String(36),
        db.ForeignKey("kanban_columns.id", ondelete="CASCADE"),
        nullable=False,
    )
    card_number = db.Column(db.Integer, nullable=True, unique=True)
    title = db.Column(db.String(500), nullable=False)
    description = db.Column(db.Text, default="")
    position = db.Column(db.Integer, nullable=False, default=0)
    labels = db.Column(db.Text, default="[]")
    comments = db.Column(db.Text, default="[]")
    prospect_id = db.Column(
        db.String(36),
        db.ForeignKey("prospects.id"),
        nullable=True,
    )
    created_at = db.Column(
        db.DateTime(timezone=True), server_default=db.func.now()
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        server_default=db.func.now(),
        onupdate=db.func.now(),
    )

    prospect = db.relationship("Prospect", foreign_keys=[prospect_id])

    def __repr__(self):
        return f"<KanbanCard {self.title[:40]}>"
