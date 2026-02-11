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
from app.models.audit import AuditEvent
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
# Email Notifications
# ──────────────────────────────────────────────

def _send_activation_email(workspace_id, site_slug):
    """Send a subscription-activated email to all workspace owners.

    Called after the subscription is created/synced — both from the
    webhook path and the checkout_status fallback.
    """
    try:
        from app.models.workspace import Workspace, WorkspaceMember
        from app.models.user import User
        from app.services.email_service import send_email

        workspace = db.session.get(Workspace, workspace_id)
        if not workspace:
            return

        app_base_url = current_app.config["APP_BASE_URL"]
        dashboard_url = f"{app_base_url}/{site_slug}/dashboard"
        billing_url = f"{app_base_url}/{site_slug}/billing"

        # Send to all owners of this workspace
        owners = (
            WorkspaceMember.query
            .filter_by(workspace_id=workspace_id, role="owner")
            .all()
        )
        for member in owners:
            user = db.session.get(User, member.user_id)
            if user and user.email:
                send_email(
                    to=user.email,
                    subject=f"Subscription activated — {workspace.name}",
                    template="emails/subscription_activated.html",
                    context={
                        "business_name": workspace.name,
                        "customer_name": user.full_name or "",
                        "dashboard_url": dashboard_url,
                        "billing_url": billing_url,
                    },
                )
                logger.info(f"Activation email sent to {user.email} for workspace {workspace_id}")
    except Exception as e:
        # Never let email failure break the checkout flow
        logger.error(f"Failed to send activation email for workspace {workspace_id}: {e}")


# ──────────────────────────────────────────────
# Checkout & Portal Sessions
# ──────────────────────────────────────────────

def create_checkout_session(workspace_id, site_id, site_slug,
                            customer_email=None, customer_name=None):
    """Create a Stripe Checkout Session for subscription + setup fee.

    Gets or creates a Stripe Customer for this workspace, then creates
    a checkout session with:
      - $191 setup fee (STRIPE_SETUP_PRICE_ID) + $59 first month
        = $250 total at checkout (matches advertised price)
      - Recurring $59/mo subscription (STRIPE_BASIC_PRICE_ID)
      - No trial — Stripe shows "Subscribe" not "Start trial"

    Args:
        customer_email: The logged-in user's email (set on Stripe customer
                        so receipts go to the right person).
        customer_name:  The logged-in user's full name.

    Returns the Stripe checkout session URL.
    Raises stripe.error.StripeError on API failures.
    """
    stripe.api_key = current_app.config["STRIPE_SECRET_KEY"]
    app_base_url = current_app.config["APP_BASE_URL"]
    setup_price_id = current_app.config["STRIPE_SETUP_PRICE_ID"]
    basic_price_id = current_app.config["STRIPE_BASIC_PRICE_ID"]

    # Get or create Stripe customer
    billing_customer = BillingCustomer.query.filter_by(
        workspace_id=workspace_id
    ).first()

    if billing_customer:
        stripe_customer_id = billing_customer.stripe_customer_id
        # Ensure the Stripe customer has the correct email/name
        # (may be missing if created before this fix)
        try:
            update_params = {}
            if customer_email:
                update_params["email"] = customer_email
            if customer_name:
                update_params["name"] = customer_name
            if update_params:
                stripe.Customer.modify(stripe_customer_id, **update_params)
        except stripe.error.InvalidRequestError:
            pass  # Will be handled by the "No such customer" fallback below
    else:
        stripe_customer_id = None

    if not stripe_customer_id:
        # Create a new Stripe customer with email + name
        customer_params = {
            "metadata": {
                "workspace_id": str(workspace_id),
                "site_slug": site_slug,
            }
        }
        if customer_email:
            customer_params["email"] = customer_email
        if customer_name:
            customer_params["name"] = customer_name
        customer = stripe.Customer.create(**customer_params)
        stripe_customer_id = customer.id
        get_or_create_billing_customer(workspace_id, stripe_customer_id)

    def _create_session(customer_id):
        return stripe.checkout.Session.create(
            mode="subscription",
            customer=customer_id,
            customer_update={"name": "auto", "address": "auto"},
            line_items=[
                {"price": setup_price_id, "quantity": 1},   # $191 one-time setup fee
                {"price": basic_price_id, "quantity": 1},    # $59/mo recurring
            ],
            success_url=(
                f"{app_base_url}/{site_slug}/billing/success"
                f"?session_id={{CHECKOUT_SESSION_ID}}"
            ),
            cancel_url=f"{app_base_url}/{site_slug}/billing/cancel",
            custom_text={
                "submit": {
                    "message": "Your $59/month subscription begins 30 days from today."
                },
            },
            metadata={
                "workspace_id": str(workspace_id),
                "site_id": str(site_id),
                "site_slug": site_slug,
            },
        )

    try:
        session = _create_session(stripe_customer_id)
    except stripe.error.InvalidRequestError as e:
        # Stored customer may be from Test mode or another account (e.g. after switching to Live)
        if "No such customer" in str(e) and billing_customer:
            fallback_params = {
                "metadata": {
                    "workspace_id": str(workspace_id),
                    "site_slug": site_slug,
                }
            }
            if customer_email:
                fallback_params["email"] = customer_email
            if customer_name:
                fallback_params["name"] = customer_name
            customer = stripe.Customer.create(**fallback_params)
            stripe_customer_id = customer.id
            billing_customer.stripe_customer_id = stripe_customer_id
            db.session.commit()
            session = _create_session(stripe_customer_id)
        else:
            raise

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

    is_cancelling = (
        sub.get("cancel_at_period_end", False)
        or sub.get("cancel_at") is not None
    )

    upsert_subscription(
        workspace_id=workspace_id,
        stripe_subscription_id=stripe_subscription_id,
        status=sub.get("status", "active"),
        stripe_price_id=stripe_price_id,
        current_period_end=current_period_end,
        cancel_at_period_end=is_cancelling,
        app_config=current_app.config,
    )

    derive_site_status(workspace_id, sub.get("status", "active"))

    log_billing_audit(workspace_id, "subscription.created", {
        "stripe_subscription_id": stripe_subscription_id,
        "plan": get_plan_from_price_id(stripe_price_id, current_app.config),
        "site_id": site_id,
    })

    # ── Auto-convert prospect to client on first payment ──
    _auto_convert_prospect(workspace_id)

    # ── Send activation email to the client ──
    site_slug = metadata.get("site_slug", "")
    _send_activation_email(workspace_id, site_slug)


def _auto_convert_prospect(workspace_id):
    """If a prospect is linked to this workspace and not yet converted,
    mark it as converted now that payment has been received.

    Uses flush() so the caller controls the commit boundary.
    """
    from app.models.workspace import Workspace
    from app.models.prospect import Prospect

    workspace = db.session.get(Workspace, workspace_id)
    if not workspace or not workspace.prospect_id:
        return

    prospect = db.session.get(Prospect, workspace.prospect_id)
    if not prospect or prospect.status == "converted":
        return

    old_status = prospect.status
    prospect.status = "converted"
    prospect.workspace_id = workspace.id

    db.session.add(AuditEvent(
        action="prospect.auto_converted",
        metadata_={
            "prospect_id": prospect.id,
            "workspace_id": workspace_id,
            "old_status": old_status,
            "reason": "stripe payment completed",
        },
    ))
    db.session.flush()
    logger.info(f"Auto-converted prospect {prospect.id} ({prospect.business_name}) to client")


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

    # Stripe uses cancel_at_period_end OR cancel_at (a future timestamp)
    # to indicate the subscription is set to cancel. Treat either as cancelling.
    is_cancelling = (
        sub_data.get("cancel_at_period_end", False)
        or sub_data.get("cancel_at") is not None
    )

    upsert_subscription(
        workspace_id=workspace_id,
        stripe_subscription_id=stripe_subscription_id,
        status=status,
        stripe_price_id=stripe_price_id,
        current_period_end=current_period_end,
        cancel_at_period_end=is_cancelling,
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
