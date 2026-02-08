"""Tenant middleware — resolves site_slug to workspace context.

Runs before every request to portal routes (/<site_slug>/*).
Sets g.workspace_id, g.workspace, g.site, g.subscription, g.access_level.

Access levels (computed from billing_subscriptions.status):
    "full"       — active or trialing subscription
    "read_only"  — past_due (grace period)
    "blocked"    — canceled, unpaid, incomplete_expired
    "subscribe"  — no subscription exists yet
"""

from flask import abort, g, request

from app.extensions import db
from app.models.site import Site
from app.models.billing import BillingSubscription


def resolve_tenant():
    """Before-request hook for portal routes.

    Extracts site_slug from the URL, loads the workspace context,
    and computes the access level from subscription status.

    Only runs on routes that have a `site_slug` URL parameter.
    Skips static files, auth routes, admin routes, and webhooks.
    """
    # Only process requests that have a site_slug view arg
    if request.view_args is None:
        return
    site_slug = request.view_args.get("site_slug")
    if site_slug is None:
        return

    # Skip non-portal routes (static, auth, admin, webhooks)
    # These are handled by their own blueprints
    path = request.path
    if path.startswith(("/static/", "/auth/", "/admin/", "/stripe/")):
        return

    # --- Resolve site from slug ---
    site = Site.query.filter_by(site_slug=site_slug).first()
    if site is None:
        abort(404)

    workspace = site.workspace

    # --- Set tenant context on g ---
    g.site = site
    g.workspace = workspace
    g.workspace_id = workspace.id

    # --- Resolve subscription ---
    subscription = BillingSubscription.query.filter_by(
        workspace_id=workspace.id
    ).order_by(BillingSubscription.created_at.desc()).first()

    g.subscription = subscription

    # --- Compute access level ---
    if subscription is None:
        g.access_level = "subscribe"
    elif subscription.status in ("active", "trialing"):
        g.access_level = "full"
    elif subscription.status == "past_due":
        g.access_level = "read_only"
    else:
        # canceled, unpaid, incomplete_expired
        g.access_level = "blocked"


def init_tenant_middleware(app):
    """Register the tenant resolver as a before_request hook."""
    app.before_request(resolve_tenant)
