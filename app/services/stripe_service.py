"""Stripe service — all Stripe API calls and webhook handling.

Responsible for:
- Creating Stripe Checkout Sessions (subscriptions)
- Creating Stripe Customer Portal Sessions
- Handling incoming webhooks with signature verification
- Dispatching to event-specific handlers
- Idempotency via stripe_events table
"""

import logging
from datetime import datetime, timezone

import stripe
from flask import current_app

from app.extensions import db
from app.models.billing import BillingCustomer, BillingSubscription
from app.models.stripe_event import StripeEvent
from app.services.billing_service import (
    derive_site_status,
    get_or_create_billing_customer,
    get_plan_from_price_id,
    get_workspace_id_from_stripe_customer,
    log_billing_audit,
    upsert_subscription,
)

logger = logging.getLogger(__name__)


def _extract_period_end(sub_data):
    """Extract current_period_end from a Stripe subscription object.

    In newer Stripe API versions, current_period_end has moved from the
    subscription top level to items.data[0].current_period_end.
    This helper checks both locations.

    Returns a timezone-aware datetime or None.
    """
    # Try top-level first (older API versions / webhook payloads)
    ts = sub_data.get("current_period_end")

    # Fall back to items.data[0].current_period_end (newer SDK)
    if not ts:
        items = sub_data.get("items")
        if items and items.get("data") and len(items["data"]) > 0:
            ts = items["data"][0].get("current_period_end")

    if ts:
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    return None


# ──────────────────────────────────────────────
# Checkout & Portal Sessions
# ──────────────────────────────────────────────

def create_checkout_session(workspace_id, site_id, price_id, site_slug):
    """Create a Stripe Checkout Session for a subscription.

    Gets or creates a Stripe Customer for this workspace, then creates
    a checkout session with workspace/site metadata.

    Returns the Stripe checkout session URL.
    Raises stripe.error.StripeError on API failures.
    """
    stripe.api_key = current_app.config["STRIPE_SECRET_KEY"]
    app_base_url = current_app.config["APP_BASE_URL"]

    # Get or create Stripe customer
    billing_customer = BillingCustomer.query.filter_by(
        workspace_id=workspace_id
    ).first()

    if billing_customer:
        stripe_customer_id = billing_customer.stripe_customer_id
    else:
        # Create a new Stripe customer
        customer = stripe.Customer.create(
            metadata={
                "workspace_id": str(workspace_id),
                "site_slug": site_slug,
            }
        )
        stripe_customer_id = customer.id
        get_or_create_billing_customer(workspace_id, stripe_customer_id)

    # Create checkout session
    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=stripe_customer_id,
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=(
            f"{app_base_url}/{site_slug}/billing/success"
            f"?session_id={{CHECKOUT_SESSION_ID}}"
        ),
        cancel_url=f"{app_base_url}/{site_slug}/billing/cancel",
        metadata={
            "workspace_id": str(workspace_id),
            "site_id": str(site_id),
            "site_slug": site_slug,
        },
    )

    return session.url


def create_portal_session(workspace_id, site_slug):
    """Create a Stripe Customer Portal Session.

    Allows the customer to manage their subscription (update payment,
    cancel, change plan) via Stripe's hosted portal.

    Returns the portal session URL.
    Raises ValueError if no billing customer exists.
    Raises stripe.error.StripeError on API failures.
    """
    stripe.api_key = current_app.config["STRIPE_SECRET_KEY"]
    app_base_url = current_app.config["APP_BASE_URL"]

    billing_customer = BillingCustomer.query.filter_by(
        workspace_id=workspace_id
    ).first()

    if not billing_customer:
        raise ValueError("No billing customer found for this workspace")

    session = stripe.billing_portal.Session.create(
        customer=billing_customer.stripe_customer_id,
        return_url=f"{app_base_url}/{site_slug}/dashboard",
    )

    return session.url


# ──────────────────────────────────────────────
# Webhook Handling
# ──────────────────────────────────────────────

def verify_webhook_signature(payload, sig_header):
    """Verify Stripe webhook signature and construct the event.

    Returns the verified Stripe event object.
    Raises stripe.error.SignatureVerificationError on invalid signature.
    """
    webhook_secret = current_app.config["STRIPE_WEBHOOK_SECRET"]
    return stripe.Webhook.construct_event(payload, sig_header, webhook_secret)


def handle_webhook_event(event):
    """Process a verified Stripe webhook event.

    Idempotency: checks stripe_events table before processing.
    If the event was already processed, returns immediately.

    Returns (success: bool, message: str).
    """
    event_id = event["id"]
    event_type = event["type"]

    # --- Idempotency check ---
    existing = StripeEvent.query.filter_by(
        stripe_event_id=event_id
    ).first()
    if existing:
        logger.info(f"Duplicate webhook event {event_id}, skipping")
        return True, "already_processed"

    # --- Route to handler ---
    handlers = {
        "checkout.session.completed": _handle_checkout_completed,
        "customer.subscription.updated": _handle_subscription_updated,
        "customer.subscription.deleted": _handle_subscription_deleted,
        "invoice.payment_failed": _handle_payment_failed,
        "invoice.payment_succeeded": _handle_payment_succeeded,
    }

    handler = handlers.get(event_type)
    if handler:
        try:
            handler(event)
        except Exception as e:
            logger.error(f"Error handling {event_type}: {e}", exc_info=True)
            db.session.rollback()
            return False, str(e)

    # --- Record event for idempotency ---
    stripe_event = StripeEvent(
        stripe_event_id=event_id,
        event_type=event_type,
    )
    db.session.add(stripe_event)
    db.session.commit()

    return True, "processed"


# ──────────────────────────────────────────────
# Event Handlers
# ──────────────────────────────────────────────

def _handle_checkout_completed(event):
    """Handle checkout.session.completed.

    Extracts workspace_id + site_id from metadata, creates/updates the
    billing subscription, and derives site.status.
    """
    session = event["data"]["object"]
    metadata = session.get("metadata", {})

    workspace_id = metadata.get("workspace_id")
    site_id = metadata.get("site_id")
    stripe_subscription_id = session.get("subscription")
    stripe_customer_id = session.get("customer")

    if not workspace_id or not stripe_subscription_id:
        logger.warning("checkout.session.completed missing workspace_id or subscription")
        return

    # Ensure billing customer exists
    get_or_create_billing_customer(workspace_id, stripe_customer_id)

    # Retrieve full subscription from Stripe for details
    stripe.api_key = current_app.config["STRIPE_SECRET_KEY"]
    sub = stripe.Subscription.retrieve(stripe_subscription_id)

    stripe_price_id = None
    if sub.get("items") and sub["items"].get("data"):
        stripe_price_id = sub["items"]["data"][0].get("price", {}).get("id")

    current_period_end = _extract_period_end(sub)

    upsert_subscription(
        workspace_id=workspace_id,
        stripe_subscription_id=stripe_subscription_id,
        status=sub.get("status", "active"),
        stripe_price_id=stripe_price_id,
        current_period_end=current_period_end,
        cancel_at_period_end=sub.get("cancel_at_period_end", False),
        app_config=current_app.config,
    )

    derive_site_status(workspace_id, sub.get("status", "active"))

    log_billing_audit(workspace_id, "subscription.created", {
        "stripe_subscription_id": stripe_subscription_id,
        "plan": get_plan_from_price_id(stripe_price_id, current_app.config),
        "site_id": site_id,
    })


def _handle_subscription_updated(event):
    """Handle customer.subscription.updated.

    Updates subscription status, period end, cancel flag, and derives site.status.
    """
    sub_data = event["data"]["object"]
    stripe_subscription_id = sub_data.get("id")
    stripe_customer_id = sub_data.get("customer")

    # Look up workspace from existing subscription or customer
    existing_sub = BillingSubscription.query.filter_by(
        stripe_subscription_id=stripe_subscription_id
    ).first()

    if existing_sub:
        workspace_id = existing_sub.workspace_id
    else:
        workspace_id = get_workspace_id_from_stripe_customer(stripe_customer_id)

    if not workspace_id:
        logger.warning(
            f"subscription.updated: cannot find workspace for sub={stripe_subscription_id}"
        )
        return

    stripe_price_id = None
    if sub_data.get("items") and sub_data["items"].get("data"):
        stripe_price_id = sub_data["items"]["data"][0].get("price", {}).get("id")

    current_period_end = _extract_period_end(sub_data)

    status = sub_data.get("status", "active")

    upsert_subscription(
        workspace_id=workspace_id,
        stripe_subscription_id=stripe_subscription_id,
        status=status,
        stripe_price_id=stripe_price_id,
        current_period_end=current_period_end,
        cancel_at_period_end=sub_data.get("cancel_at_period_end", False),
        app_config=current_app.config,
    )

    derive_site_status(workspace_id, status)

    log_billing_audit(workspace_id, "subscription.updated", {
        "stripe_subscription_id": stripe_subscription_id,
        "status": status,
        "cancel_at_period_end": sub_data.get("cancel_at_period_end", False),
    })


def _handle_subscription_deleted(event):
    """Handle customer.subscription.deleted.

    Marks subscription as canceled and derives site.status = paused.
    """
    sub_data = event["data"]["object"]
    stripe_subscription_id = sub_data.get("id")

    existing_sub = BillingSubscription.query.filter_by(
        stripe_subscription_id=stripe_subscription_id
    ).first()

    if not existing_sub:
        logger.warning(
            f"subscription.deleted: no local record for sub={stripe_subscription_id}"
        )
        return

    existing_sub.status = "canceled"
    existing_sub.cancel_at_period_end = False
    db.session.flush()

    derive_site_status(existing_sub.workspace_id, "canceled")

    log_billing_audit(existing_sub.workspace_id, "subscription.deleted", {
        "stripe_subscription_id": stripe_subscription_id,
    })


def _handle_payment_failed(event):
    """Handle invoice.payment_failed.

    Updates subscription status to past_due if not already.
    """
    invoice = event["data"]["object"]
    stripe_customer_id = invoice.get("customer")
    stripe_subscription_id = invoice.get("subscription")

    workspace_id = get_workspace_id_from_stripe_customer(stripe_customer_id)
    if not workspace_id:
        logger.warning(
            f"invoice.payment_failed: cannot find workspace for customer={stripe_customer_id}"
        )
        return

    if stripe_subscription_id:
        sub = BillingSubscription.query.filter_by(
            stripe_subscription_id=stripe_subscription_id
        ).first()
        if sub and sub.status != "past_due":
            sub.status = "past_due"
            db.session.flush()

    log_billing_audit(workspace_id, "invoice.payment_failed", {
        "stripe_subscription_id": stripe_subscription_id,
        "amount_due": invoice.get("amount_due"),
    })


def _handle_payment_succeeded(event):
    """Handle invoice.payment_succeeded.

    Ensures subscription status reflects active.
    """
    invoice = event["data"]["object"]
    stripe_customer_id = invoice.get("customer")
    stripe_subscription_id = invoice.get("subscription")

    workspace_id = get_workspace_id_from_stripe_customer(stripe_customer_id)
    if not workspace_id:
        logger.warning(
            f"invoice.payment_succeeded: cannot find workspace for customer={stripe_customer_id}"
        )
        return

    if stripe_subscription_id:
        sub = BillingSubscription.query.filter_by(
            stripe_subscription_id=stripe_subscription_id
        ).first()
        if sub and sub.status in ("past_due", "unpaid"):
            sub.status = "active"
            db.session.flush()
            derive_site_status(workspace_id, "active")

    log_billing_audit(workspace_id, "invoice.payment_succeeded", {
        "stripe_subscription_id": stripe_subscription_id,
        "amount_paid": invoice.get("amount_paid"),
    })
