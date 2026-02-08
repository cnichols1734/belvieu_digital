"""User model.

Stores authentication credentials and profile info.
Flask-Login integration via UserMixin.
"""

import uuid

from flask_login import UserMixin

from app.extensions import db


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(
        db.String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(255))
    is_admin = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(
        db.DateTime(timezone=True), server_default=db.func.now()
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        server_default=db.func.now(),
        onupdate=db.func.now(),
    )

    # --- Relationships ---
    workspace_memberships = db.relationship(
        "WorkspaceMember", back_populates="user", lazy="dynamic"
    )
    authored_tickets = db.relationship(
        "Ticket",
        foreign_keys="Ticket.author_user_id",
        back_populates="author",
        lazy="dynamic",
    )
    assigned_tickets = db.relationship(
        "Ticket",
        foreign_keys="Ticket.assigned_to_user_id",
        back_populates="assigned_to",
        lazy="dynamic",
    )
    ticket_messages = db.relationship(
        "TicketMessage", back_populates="author", lazy="dynamic"
    )
    audit_events = db.relationship(
        "AuditEvent", back_populates="actor", lazy="dynamic"
    )

    def __repr__(self):
        return f"<User {self.email}>"
