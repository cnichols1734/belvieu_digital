"""Prospect model (Lite CRM).

Tracks businesses from discovery through conversion or decline.
Pipeline: researching -> site_built -> pitched -> converted -> declined
"""

import uuid

from app.extensions import db


class Prospect(db.Model):
    __tablename__ = "prospects"

    # -- Valid statuses for pipeline tracking --
    STATUSES = [
        "researching",
        "site_built",
        "pitched",
        "converted",
        "declined",
    ]

    id = db.Column(
        db.String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    business_name = db.Column(db.String(255), nullable=False)
    contact_name = db.Column(db.String(255), nullable=True)
    contact_email = db.Column(db.String(255), nullable=True)
    contact_phone = db.Column(db.String(50), nullable=True)
    source = db.Column(
        db.String(50), nullable=False
    )  # google_maps | facebook | yelp | referral | other
    source_url = db.Column(
        db.String(500), nullable=True
    )  # link to Maps/FB listing
    notes = db.Column(db.Text, nullable=True)  # free-form notes
    demo_url = db.Column(
        db.String(500), nullable=True
    )  # cloudflare .dev preview link
    status = db.Column(db.String(50), default="researching", nullable=False)
    workspace_id = db.Column(
        db.String(36),
        db.ForeignKey("workspaces.id", use_alter=True, name="fk_prospects_workspace_id"),
        nullable=True,
    )  # set when converted
    created_at = db.Column(
        db.DateTime(timezone=True), server_default=db.func.now()
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        server_default=db.func.now(),
        onupdate=db.func.now(),
    )

    # --- Relationships ---
    # The workspace created when this prospect converted (via prospect.workspace_id).
    # NOT a back_populates of Workspace.prospect — they use different FKs.
    workspace = db.relationship(
        "Workspace",
        foreign_keys=[workspace_id],
        uselist=False,
    )

    def __repr__(self):
        return f"<Prospect {self.business_name} ({self.status})>"
