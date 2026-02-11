"""Site model.

Represents a deployed website for a workspace.
site.status is a DERIVED / PRESENTATION value -- entitlement gating
uses billing_subscriptions.status (not this field).
"""

import uuid

from app.extensions import db


class Site(db.Model):
    __tablename__ = "sites"

    # -- Valid statuses (presentation only, NOT used for access gating) --
    STATUSES = ["demo", "active", "paused", "cancelled"]

    id = db.Column(
        db.String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    workspace_id = db.Column(
        db.String(36), db.ForeignKey("workspaces.id"), nullable=False
    )
    site_slug = db.Column(db.String(100), unique=True, nullable=False)
    display_name = db.Column(db.String(255), nullable=True)
    published_url = db.Column(
        db.String(500), nullable=True
    )  # cloudflare .dev preview link
    custom_domain = db.Column(
        db.String(255), nullable=True
    )  # bought domain after purchase
    status = db.Column(
        db.String(50), default="demo", nullable=False
    )  # demo | active | paused | cancelled

    # --- Domain selection (client intent, set before subscription) ---
    domain_choice = db.Column(
        db.String(30), nullable=True
    )  # search_new | own_domain | keep_subdomain
    requested_domain = db.Column(
        db.String(255), nullable=True
    )  # domain they want (e.g. "mariospizza.com")
    requested_domain_price = db.Column(
        db.Float, nullable=True
    )  # annual price in USD from Cloudflare pricing
    domain_self_purchase = db.Column(
        db.Boolean, default=False
    )  # True if domain is over budget; client buys it themselves
    domain_choice_at = db.Column(
        db.DateTime(timezone=True), nullable=True
    )  # when the client made their selection

    created_at = db.Column(
        db.DateTime(timezone=True), server_default=db.func.now()
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        server_default=db.func.now(),
        onupdate=db.func.now(),
    )

    # --- Relationships ---
    workspace = db.relationship("Workspace", back_populates="sites")
    invites = db.relationship(
        "WorkspaceInvite", back_populates="site", lazy="dynamic"
    )
    tickets = db.relationship(
        "Ticket", back_populates="site", lazy="dynamic"
    )

    def __repr__(self):
        return f"<Site {self.site_slug} ({self.status})>"
