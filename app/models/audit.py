"""Audit event model.

Logs all significant actions (user registration, status changes, admin
actions, etc.) for the activity feed and debugging.
"""

import uuid

from app.extensions import db


class AuditEvent(db.Model):
    __tablename__ = "audit_events"

    id = db.Column(
        db.String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    workspace_id = db.Column(
        db.String(36), db.ForeignKey("workspaces.id"), nullable=True
    )
    actor_user_id = db.Column(
        db.String(36), db.ForeignKey("users.id"), nullable=True
    )
    action = db.Column(db.String(255), nullable=False)  # e.g. "user.registered"
    metadata_ = db.Column(
        "metadata", db.JSON, default=dict
    )  # extra context, named metadata_ to avoid Python builtin clash
    created_at = db.Column(
        db.DateTime(timezone=True), server_default=db.func.now()
    )

    # --- Relationships ---
    workspace = db.relationship("Workspace", back_populates="audit_events")
    actor = db.relationship("User", back_populates="audit_events")

    def __repr__(self):
        return f"<AuditEvent {self.action}>"
