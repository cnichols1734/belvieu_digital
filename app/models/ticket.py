"""Ticket models.

- Ticket: support ticket tied to a workspace + site.
- TicketMessage: threaded replies on a ticket.

Includes assigned_to, last_activity_at, and is_internal on messages
from day one per plan specs.
"""

import uuid

from app.extensions import db


class Ticket(db.Model):
    __tablename__ = "tickets"

    # -- Valid statuses --
    STATUSES = ["open", "in_progress", "waiting_on_client", "done"]

    # -- Valid status transitions (enforced in ticket_service) --
    VALID_TRANSITIONS = {
        "open": ["in_progress", "done"],
        "in_progress": ["waiting_on_client", "done"],
        "waiting_on_client": ["in_progress", "done"],
    }

    # -- Valid categories --
    CATEGORIES = ["content_update", "bug", "question"]

    # -- Valid priorities --
    PRIORITIES = ["low", "normal", "high"]

    id = db.Column(
        db.String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    workspace_id = db.Column(
        db.String(36), db.ForeignKey("workspaces.id"), nullable=False
    )
    site_id = db.Column(
        db.String(36), db.ForeignKey("sites.id"), nullable=False
    )
    author_user_id = db.Column(
        db.String(36), db.ForeignKey("users.id"), nullable=False
    )
    assigned_to_user_id = db.Column(
        db.String(36), db.ForeignKey("users.id"), nullable=True
    )
    subject = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=False)
    category = db.Column(
        db.String(50), nullable=True
    )  # content_update | bug | question
    status = db.Column(
        db.String(50), default="open", nullable=False
    )  # open | in_progress | waiting_on_client | done
    priority = db.Column(
        db.String(50), default="normal", nullable=False
    )  # low | normal | high
    last_activity_at = db.Column(
        db.DateTime(timezone=True), server_default=db.func.now()
    )
    created_at = db.Column(
        db.DateTime(timezone=True), server_default=db.func.now()
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        server_default=db.func.now(),
        onupdate=db.func.now(),
    )

    # --- Relationships ---
    workspace = db.relationship("Workspace", back_populates="tickets")
    site = db.relationship("Site", back_populates="tickets")
    author = db.relationship(
        "User",
        foreign_keys=[author_user_id],
        back_populates="authored_tickets",
    )
    assigned_to = db.relationship(
        "User",
        foreign_keys=[assigned_to_user_id],
        back_populates="assigned_tickets",
    )
    messages = db.relationship(
        "TicketMessage",
        back_populates="ticket",
        lazy="dynamic",
        order_by="TicketMessage.created_at",
    )

    def __repr__(self):
        return f"<Ticket {self.subject[:30]} ({self.status})>"


class TicketMessage(db.Model):
    __tablename__ = "ticket_messages"

    id = db.Column(
        db.String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    ticket_id = db.Column(
        db.String(36), db.ForeignKey("tickets.id"), nullable=False
    )
    author_user_id = db.Column(
        db.String(36), db.ForeignKey("users.id"), nullable=False
    )
    message = db.Column(db.Text, nullable=False)
    is_internal = db.Column(
        db.Boolean, default=False
    )  # internal notes visible to admin only
    created_at = db.Column(
        db.DateTime(timezone=True), server_default=db.func.now()
    )

    # --- Relationships ---
    ticket = db.relationship("Ticket", back_populates="messages")
    author = db.relationship("User", back_populates="ticket_messages")
    attachments = db.relationship(
        "TicketAttachment",
        back_populates="message",
        lazy="joined",
        order_by="TicketAttachment.created_at",
    )

    def __repr__(self):
        return f"<TicketMessage ticket={self.ticket_id} internal={self.is_internal}>"


class TicketAttachment(db.Model):
    """File attachment on a ticket message (images, PDFs, etc.).

    Files are stored in Supabase Storage (prod) or local filesystem (dev).
    """
    __tablename__ = "ticket_attachments"

    id = db.Column(
        db.String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    message_id = db.Column(
        db.String(36), db.ForeignKey("ticket_messages.id"), nullable=False
    )
    ticket_id = db.Column(
        db.String(36), db.ForeignKey("tickets.id"), nullable=False
    )
    filename = db.Column(db.String(255), nullable=False)       # original filename
    storage_path = db.Column(db.String(500), nullable=False)   # path in bucket / on disk
    content_type = db.Column(db.String(100), nullable=False)   # e.g. image/png, application/pdf
    file_size = db.Column(db.Integer, nullable=False)          # bytes
    public_url = db.Column(db.String(1000), nullable=True)     # public URL for display
    created_at = db.Column(
        db.DateTime(timezone=True), server_default=db.func.now()
    )

    # --- Relationships ---
    message = db.relationship("TicketMessage", back_populates="attachments")
    ticket = db.relationship("Ticket")

    @property
    def is_image(self):
        return self.content_type and self.content_type.startswith("image/")

    @property
    def is_pdf(self):
        return self.content_type == "application/pdf"

    @property
    def human_size(self):
        """Return human-readable file size."""
        if self.file_size < 1024:
            return f"{self.file_size} B"
        elif self.file_size < 1024 * 1024:
            return f"{self.file_size / 1024:.1f} KB"
        else:
            return f"{self.file_size / (1024 * 1024):.1f} MB"

    def __repr__(self):
        return f"<TicketAttachment {self.filename} ({self.content_type})>"
