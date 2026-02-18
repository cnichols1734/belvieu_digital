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
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models.site import Site
from app.models.billing import BillingSubscription
from app.models.workspace import Workspace


def resolve_tenant():
    """Before-request hook for portal routes.

    Extracts site_slug from the URL, loads the workspace context,
    and computes the access level from subscription status.

    Only runs on routes that have a `site_slug` URL parameter.
    Skips static files, auth routes, admin routes, and webhooks.
    """
    if request.view_args is None:
        return
    site_slug = request.view_args.get("site_slug")
    if site_slug is None:
        return

    path = request.path
    if path.startswith(("/static/", "/auth/", "/admin/", "/stripe/")):
        return

    # Single query: load site + workspace in one JOIN
    site = (
        Site.query
        .options(joinedload(Site.workspace))
        .filter_by(site_slug=site_slug)
        .first()
    )
    if site is None:
        abort(404)

    workspace = site.workspace

    g.site = site
    g.workspace = workspace
    g.workspace_id = workspace.id

    # Subscription query (still needed, but just 1 query)
    subscription = (
        BillingSubscription.query
        .filter_by(workspace_id=workspace.id)
        .order_by(BillingSubscription.created_at.desc())
        .first()
    )

    g.subscription = subscription

    if subscription is None:
        g.access_level = "subscribe"
    elif subscription.status in ("active", "trialing"):
        g.access_level = "full"
    elif subscription.status == "past_due":
        g.access_level = "read_only"
    else:
        g.access_level = "blocked"


def init_tenant_middleware(app):
    """Register the tenant resolver as a before_request hook."""
    app.before_request(resolve_tenant)
