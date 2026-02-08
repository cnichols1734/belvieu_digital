"""Billing models.

- BillingCustomer: links a workspace to a Stripe customer ID.
- BillingSubscription: tracks subscription state synced from Stripe webhooks.
  billing_subscriptions.status is the source of truth for entitlement gating.
"""

import uuid

from app.extensions import db


class BillingCustomer(db.Model):
    __tablename__ = "billing_customers"

    id = db.Column(
        db.String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    workspace_id = db.Column(
        db.String(36),
        db.ForeignKey("workspaces.id"),
        unique=True,
        nullable=False,
    )
    stripe_customer_id = db.Column(
        db.String(255), unique=True, nullable=False
    )
    created_at = db.Column(
        db.DateTime(timezone=True), server_default=db.func.now()
    )

    # --- Relationships ---
    workspace = db.relationship("Workspace", back_populates="billing_customer")

    def __repr__(self):
        return f"<BillingCustomer stripe={self.stripe_customer_id}>"


class BillingSubscription(db.Model):
    __tablename__ = "billing_subscriptions"

    # -- Valid statuses (synced from Stripe) --
    STATUSES = [
        "active",
        "past_due",
        "canceled",
        "trialing",
        "unpaid",
        "incomplete_expired",
    ]

    id = db.Column(
        db.String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    workspace_id = db.Column(
        db.String(36), db.ForeignKey("workspaces.id"), nullable=False
    )
    stripe_subscription_id = db.Column(
        db.String(255), unique=True, nullable=False
    )
    stripe_price_id = db.Column(db.String(255), nullable=True)
    plan = db.Column(db.String(50), nullable=True)  # basic | pro
    status = db.Column(
        db.String(50), nullable=False
    )  # active | past_due | canceled | trialing | unpaid | incomplete_expired
    current_period_end = db.Column(
        db.DateTime(timezone=True), nullable=True
    )
    cancel_at_period_end = db.Column(db.Boolean, default=False)
    created_at = db.Column(
        db.DateTime(timezone=True), server_default=db.func.now()
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        server_default=db.func.now(),
        onupdate=db.func.now(),
    )

    # --- Relationships ---
    workspace = db.relationship(
        "Workspace", back_populates="billing_subscriptions"
    )

    def __repr__(self):
        return f"<BillingSubscription {self.plan} ({self.status})>"
