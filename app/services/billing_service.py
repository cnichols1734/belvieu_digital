"""Billing service — DB sync helpers and entitlement logic.

Responsible for:
- Mapping Stripe price IDs to plan names (basic / pro)
- Upserting billing_subscriptions rows from Stripe webhook data
- Deriving site.status from subscription status (presentation only)
- Getting or creating BillingCustomer records
"""

import logging
from datetime import datetime, timezone

from app.extensions import db
from app.models.billing import BillingCustomer, BillingSubscription
from app.models.site import Site
from app.models.audit import AuditEvent

logger = logging.getLogger(__name__)


def get_plan_from_price_id(price_id, app_config):
    """Map a Stripe price ID to a plan name (basic / pro).

    Returns None if the price_id doesn't match either configured plan.
    """
    if price_id == app_config.get("STRIPE_BASIC_PRICE_ID"):
        return "basic"
    elif price_id == app_config.get("STRIPE_PRO_PRICE_ID"):
        return "pro"
    return None


def get_or_create_billing_customer(workspace_id, stripe_customer_id):
    """Get existing BillingCustomer or create one.

    Returns the BillingCustomer instance (committed).
    """
    customer = BillingCustomer.query.filter_by(
        workspace_id=workspace_id
    ).first()

    if customer:
        # Update stripe_customer_id if it changed (shouldn't happen, but safety)
        if customer.stripe_customer_id != stripe_customer_id:
            customer.stripe_customer_id = stripe_customer_id
            db.session.commit()
        return customer

    # Also check by stripe_customer_id (in case workspace_id wasn't matched)
    customer = BillingCustomer.query.filter_by(
        stripe_customer_id=stripe_customer_id
    ).first()
    if customer:
        return customer

    customer = BillingCustomer(
        workspace_id=workspace_id,
        stripe_customer_id=stripe_customer_id,
    )
    db.session.add(customer)
    db.session.commit()
    return customer


def upsert_subscription(workspace_id, stripe_subscription_id, status,
                         stripe_price_id=None, current_period_end=None,
                         cancel_at_period_end=False, app_config=None):
    """Create or update a BillingSubscription from Stripe data.

    This is the core sync function called by webhook handlers.
    Returns the BillingSubscription instance.
    """
    sub = BillingSubscription.query.filter_by(
        stripe_subscription_id=stripe_subscription_id
    ).first()

    plan = None
    if stripe_price_id and app_config:
        plan = get_plan_from_price_id(stripe_price_id, app_config)

    if sub:
        sub.status = status
        if stripe_price_id:
            sub.stripe_price_id = stripe_price_id
        if plan:
            sub.plan = plan
        if current_period_end:
            sub.current_period_end = current_period_end
        sub.cancel_at_period_end = cancel_at_period_end
    else:
        sub = BillingSubscription(
            workspace_id=workspace_id,
            stripe_subscription_id=stripe_subscription_id,
            stripe_price_id=stripe_price_id,
            plan=plan,
            status=status,
            current_period_end=current_period_end,
            cancel_at_period_end=cancel_at_period_end,
        )
        db.session.add(sub)

    db.session.flush()
    return sub


def derive_site_status(workspace_id, subscription_status):
    """Update site.status as a derived presentation value.

    site.status is NOT used for access gating (that's billing_subscriptions.status).
    This is for display purposes and for knowing when to deploy/pause on Cloudflare.

    Mapping:
        active / trialing  -> 'active'
        past_due           -> 'active' (still up, portal shows warning)
        canceled / unpaid  -> 'paused'
    """
    site = Site.query.filter_by(workspace_id=workspace_id).first()
    if not site:
        logger.warning(f"No site found for workspace {workspace_id}")
        return

    if subscription_status in ("active", "trialing", "past_due"):
        site.status = "active"
    elif subscription_status in ("canceled", "unpaid", "incomplete_expired"):
        site.status = "paused"

    db.session.flush()


def log_billing_audit(workspace_id, action, metadata=None):
    """Log a billing-related audit event.

    Actor is None because webhook events are system-initiated.
    """
    event = AuditEvent(
        workspace_id=workspace_id,
        actor_user_id=None,
        action=action,
        metadata_=metadata or {},
    )
    db.session.add(event)
    db.session.flush()


def get_workspace_id_from_stripe_customer(stripe_customer_id):
    """Look up workspace_id from a Stripe customer ID.

    Returns workspace_id string or None.
    """
    customer = BillingCustomer.query.filter_by(
        stripe_customer_id=stripe_customer_id
    ).first()
    if customer:
        return customer.workspace_id
    return None
