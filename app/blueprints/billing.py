"""Billing blueprint — /<site_slug>/billing/*

Stripe Checkout, Customer Portal, success/cancel pages.

Routes:
- POST /<site_slug>/billing/checkout  — create Checkout Session, redirect to Stripe
- GET  /<site_slug>/billing/success   — post-checkout landing page
- GET  /<site_slug>/billing/cancel    — user cancelled checkout, redirect to dashboard
- POST /<site_slug>/billing/portal    — create Customer Portal Session, redirect to Stripe
- GET  /<site_slug>/billing           — billing overview (current plan, manage billing)
"""

import logging

from flask import (
    Blueprint,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user

from app.decorators import login_required_for_site
from app.services.stripe_service import create_checkout_session, create_portal_session

logger = logging.getLogger(__name__)

billing_bp = Blueprint("billing", __name__)


# ──────────────────────────────────────────────
# POST /<site_slug>/billing/checkout
# ──────────────────────────────────────────────

@billing_bp.route("/<site_slug>/billing/checkout", methods=["POST"])
@login_required_for_site
def checkout(site_slug):
    """Create a Stripe Checkout Session and redirect to Stripe.

    Single-plan checkout: $250 one-time setup fee + $59/mo subscription
    with first recurring charge deferred 30 days (first month free).
    Accessible even when access_level is 'subscribe' or 'blocked'.
    """
    try:
        checkout_url = create_checkout_session(
            workspace_id=g.workspace_id,
            site_id=g.site.id,
            site_slug=site_slug,
        )
        return redirect(checkout_url)
    except Exception as e:
        logger.error(f"Checkout error: {e}", exc_info=True)
        flash("Something went wrong starting checkout. Please try again.", "error")
        return redirect(url_for("portal.dashboard", site_slug=site_slug))


# ──────────────────────────────────────────────
# GET /<site_slug>/billing/success
# ──────────────────────────────────────────────

@billing_bp.route("/<site_slug>/billing/success")
@login_required_for_site
def checkout_success(site_slug):
    """Post-checkout landing page.

    Shows a "Payment processing..." message. The webhook will update
    the subscription status async. We show a brief success page that
    redirects to the dashboard after a few seconds.
    """
    return render_template("portal/billing_success.html")


# ──────────────────────────────────────────────
# GET /<site_slug>/billing/status — AJAX poll
# ──────────────────────────────────────────────

@billing_bp.route("/<site_slug>/billing/status")
@login_required_for_site
def checkout_status(site_slug):
    """JSON endpoint polled by the success page to check if the
    subscription is active yet.

    If the webhook hasn't arrived yet, we can use the session_id
    (passed from the success URL) to fetch the subscription directly
    from Stripe and sync it ourselves — works even without webhooks.
    """
    from flask import jsonify
    from app.models.billing import BillingSubscription

    sub = (
        BillingSubscription.query
        .filter_by(workspace_id=g.workspace_id)
        .order_by(BillingSubscription.created_at.desc())
        .first()
    )
    active = sub is not None and sub.status in ("active", "trialing")

    # If not active yet, try to sync from Stripe directly using the session_id
    if not active:
        session_id = request.args.get("session_id")
        if session_id:
            try:
                import stripe
                from datetime import datetime, timezone
                from app.extensions import db
                from app.services.billing_service import (
                    get_or_create_billing_customer,
                    upsert_subscription,
                    derive_site_status,
                    get_plan_from_price_id,
                )

                stripe.api_key = current_app.config["STRIPE_SECRET_KEY"]
                session = stripe.checkout.Session.retrieve(session_id)

                if session.get("payment_status") == "paid" and session.get("subscription"):
                    stripe_sub = stripe.Subscription.retrieve(session["subscription"])
                    stripe_customer_id = session.get("customer")

                    # Ensure billing customer exists
                    get_or_create_billing_customer(g.workspace_id, stripe_customer_id)

                    # Extract price info
                    stripe_price_id = None
                    if stripe_sub.get("items") and stripe_sub["items"].get("data"):
                        stripe_price_id = stripe_sub["items"]["data"][0].get("price", {}).get("id")

                    # Extract period end (newer Stripe SDK puts it on items, not top level)
                    from app.services.stripe_service import _extract_period_end
                    current_period_end = _extract_period_end(stripe_sub)

                    upsert_subscription(
                        workspace_id=g.workspace_id,
                        stripe_subscription_id=stripe_sub["id"],
                        status=stripe_sub.get("status", "active"),
                        stripe_price_id=stripe_price_id,
                        current_period_end=current_period_end,
                        cancel_at_period_end=stripe_sub.get("cancel_at_period_end", False),
                        app_config=current_app.config,
                    )

                    derive_site_status(g.workspace_id, stripe_sub.get("status", "active"))
                    db.session.commit()

                    active = stripe_sub.get("status") in ("active", "trialing")
                    logger.info(f"Synced subscription from Stripe session {session_id} for workspace {g.workspace_id}")
            except Exception as e:
                logger.warning(f"Failed to sync from Stripe session: {e}")

    return jsonify({"active": active})


# ──────────────────────────────────────────────
# GET /<site_slug>/billing/cancel
# ──────────────────────────────────────────────

@billing_bp.route("/<site_slug>/billing/cancel")
@login_required_for_site
def checkout_cancel(site_slug):
    """User cancelled Stripe Checkout — redirect back to dashboard."""
    flash("Checkout was cancelled. You can subscribe anytime.", "info")
    return redirect(url_for("portal.dashboard", site_slug=site_slug))


# ──────────────────────────────────────────────
# POST /<site_slug>/billing/portal
# ──────────────────────────────────────────────

@billing_bp.route("/<site_slug>/billing/portal", methods=["POST"])
@login_required_for_site
def customer_portal(site_slug):
    """Create a Stripe Customer Portal Session and redirect.

    Only accessible if a billing_customer exists (i.e., they've checked
    out at least once).
    """
    try:
        portal_url = create_portal_session(
            workspace_id=g.workspace_id,
            site_slug=site_slug,
        )
        return redirect(portal_url)
    except ValueError:
        flash("No billing account found. Please subscribe first.", "error")
        return redirect(url_for("portal.dashboard", site_slug=site_slug))
    except Exception as e:
        logger.error(f"Portal session error: {e}", exc_info=True)
        flash("Something went wrong. Please try again.", "error")
        return redirect(url_for("portal.dashboard", site_slug=site_slug))


# ──────────────────────────────────────────────
# GET /<site_slug>/billing
# ──────────────────────────────────────────────

@billing_bp.route("/<site_slug>/billing")
@login_required_for_site
def billing_overview(site_slug):
    """Billing overview page.

    Shows current plan info and 'Manage Billing' button for active
    subscribers. Redirects to subscribe page if no subscription.
    """
    if g.access_level == "subscribe":
        return render_template("portal/subscribe.html")

    return render_template("portal/billing.html")
