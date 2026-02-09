"""ProspectActivity model — outreach activity log.

Tracks outreach attempts on prospects: emails, texts, calls, notes.
Displayed as a timeline on the prospect detail page.
"""

import uuid

from app.extensions import db


class ProspectActivity(db.Model):
    __tablename__ = "prospect_activities"

    TYPES = ["email", "text", "call", "note"]

    id = db.Column(
        db.String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    prospect_id = db.Column(
        db.String(36),
        db.ForeignKey("prospects.id"),
        nullable=False,
        index=True,
    )
    activity_type = db.Column(
        db.String(50), nullable=False
    )  # email | text | call | note
    note = db.Column(db.Text, nullable=True)
    actor_user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id"),
        nullable=True,
    )
    created_at = db.Column(
        db.DateTime(timezone=True), server_default=db.func.now()
    )

    # --- Relationships ---
    prospect = db.relationship("Prospect", backref=db.backref("activities", lazy="dynamic", order_by="ProspectActivity.created_at.desc()"))
    actor = db.relationship("User", lazy="joined")

    def __repr__(self):
        return f"<ProspectActivity {self.activity_type} on {self.prospect_id}>"
