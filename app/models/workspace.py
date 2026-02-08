"""Workspace models.

- Workspace: the top-level tenant container (one per client business).
- WorkspaceMember: join table linking users to workspaces.
- WorkspaceSettings: per-workspace config (brand color, feature flags, etc.).
"""

import uuid

from app.extensions import db


class Workspace(db.Model):
    __tablename__ = "workspaces"

    id = db.Column(
        db.String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name = db.Column(db.String(255), nullable=False)
    prospect_id = db.Column(
        db.String(36),
        db.ForeignKey("prospects.id", use_alter=True, name="fk_workspaces_prospect_id"),
        nullable=True,
    )
    created_at = db.Column(
        db.DateTime(timezone=True), server_default=db.func.now()
    )

    # --- Relationships ---
    # The prospect this workspace was converted from (via workspace.prospect_id).
    # NOT a back_populates of Prospect.workspace — they use different FKs.
    prospect = db.relationship(
        "Prospect", foreign_keys=[prospect_id]
    )
    members = db.relationship(
        "WorkspaceMember", back_populates="workspace", lazy="dynamic"
    )
    settings = db.relationship(
        "WorkspaceSettings",
        back_populates="workspace",
        uselist=False,
        cascade="all, delete-orphan",
    )
    sites = db.relationship(
        "Site", back_populates="workspace", lazy="dynamic"
    )
    invites = db.relationship(
        "WorkspaceInvite", back_populates="workspace", lazy="dynamic"
    )
    billing_customer = db.relationship(
        "BillingCustomer",
        back_populates="workspace",
        uselist=False,
        cascade="all, delete-orphan",
    )
    billing_subscriptions = db.relationship(
        "BillingSubscription", back_populates="workspace", lazy="dynamic"
    )
    tickets = db.relationship(
        "Ticket", back_populates="workspace", lazy="dynamic"
    )
    audit_events = db.relationship(
        "AuditEvent", back_populates="workspace", lazy="dynamic"
    )

    def __repr__(self):
        return f"<Workspace {self.name}>"


class WorkspaceMember(db.Model):
    __tablename__ = "workspace_members"

    id = db.Column(
        db.String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id = db.Column(
        db.String(36), db.ForeignKey("users.id"), nullable=False
    )
    workspace_id = db.Column(
        db.String(36), db.ForeignKey("workspaces.id"), nullable=False
    )
    role = db.Column(db.String(50), default="owner")  # owner | member
    created_at = db.Column(
        db.DateTime(timezone=True), server_default=db.func.now()
    )

    __table_args__ = (
        db.UniqueConstraint(
            "user_id", "workspace_id", name="uq_user_workspace"
        ),
    )

    # --- Relationships ---
    user = db.relationship("User", back_populates="workspace_memberships")
    workspace = db.relationship("Workspace", back_populates="members")

    def __repr__(self):
        return f"<WorkspaceMember user={self.user_id} workspace={self.workspace_id}>"


class WorkspaceSettings(db.Model):
    __tablename__ = "workspace_settings"

    id = db.Column(
        db.String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    workspace_id = db.Column(
        db.String(36),
        db.ForeignKey("workspaces.id"),
        unique=True,
        nullable=False,
    )
    brand_color = db.Column(db.String(7), nullable=True)  # hex color
    plan_features = db.Column(db.JSON, default=dict)  # feature flags / limits
    update_allowance = db.Column(
        db.Integer, nullable=True
    )  # monthly limit, null = unlimited
    notification_prefs = db.Column(db.JSON, default=dict)
    created_at = db.Column(
        db.DateTime(timezone=True), server_default=db.func.now()
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        server_default=db.func.now(),
        onupdate=db.func.now(),
    )

    # --- Relationships ---
    workspace = db.relationship("Workspace", back_populates="settings")

    def __repr__(self):
        return f"<WorkspaceSettings workspace={self.workspace_id}>"
