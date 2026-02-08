"""Workspace invite model.

Invite-only registration: admin creates an invite token tied to a
workspace + site. Client registers by visiting the invite URL.
Tokens are one-time-use with 30-day expiration.
"""

import uuid
from datetime import datetime, timezone

from app.extensions import db


class WorkspaceInvite(db.Model):
    __tablename__ = "workspace_invites"

    id = db.Column(
        db.String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    workspace_id = db.Column(
        db.String(36), db.ForeignKey("workspaces.id"), nullable=False
    )
    site_id = db.Column(
        db.String(36), db.ForeignKey("sites.id"), nullable=False
    )
    email = db.Column(
        db.String(255), nullable=True
    )  # optional: lock invite to specific email
    token = db.Column(
        db.String(64), unique=True, nullable=False
    )  # cryptographically random
    expires_at = db.Column(
        db.DateTime(timezone=True), nullable=False
    )  # default: 30 days from creation
    used_at = db.Column(
        db.DateTime(timezone=True), nullable=True
    )  # set when consumed during registration
    created_at = db.Column(
        db.DateTime(timezone=True), server_default=db.func.now()
    )

    # --- Relationships ---
    workspace = db.relationship("Workspace", back_populates="invites")
    site = db.relationship("Site", back_populates="invites")

    @property
    def is_expired(self):
        """Check if the invite has expired."""
        now = datetime.now(timezone.utc)
        expires = self.expires_at
        # SQLite returns naive datetimes; Postgres returns aware ones.
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return now > expires

    @property
    def is_used(self):
        """Check if the invite has already been consumed."""
        return self.used_at is not None

    @property
    def is_valid(self):
        """Check if the invite can still be used."""
        return not self.is_expired and not self.is_used

    def __repr__(self):
        return f"<WorkspaceInvite token={self.token[:8]}... workspace={self.workspace_id}>"
