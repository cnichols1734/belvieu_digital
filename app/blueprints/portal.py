"""Portal blueprint — /<site_slug>/*

Client-facing dashboard and ticketing. Access gating based on subscription
status via g.access_level (set by tenant middleware).

Ticket routes:
  GET  /<site_slug>/tickets           — list all tickets for workspace
  GET/POST /<site_slug>/tickets/new   — create a new ticket
  GET  /<site_slug>/tickets/<id>      — ticket detail + message thread
  POST /<site_slug>/tickets/<id>/reply — add reply to ticket thread
"""

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
from app.extensions import db
from app.models.ticket import Ticket
from app.models.workspace import WorkspaceMember
from app.models.user import User
from app.services import ticket_service
from app.services.email_service import send_email

portal_bp = Blueprint("portal", __name__)


# ──────────────────────────────────────────────
# GET /<site_slug>/ — redirect to dashboard or login
# ──────────────────────────────────────────────

@portal_bp.route("/<site_slug>/")
def portal_root(site_slug):
    """Root portal URL — redirect to dashboard."""
    if current_user.is_authenticated:
        return redirect(url_for("portal.dashboard", site_slug=site_slug))
    return redirect(url_for("auth.login", next=f"/{site_slug}/dashboard"))


# ──────────────────────────────────────────────
# GET /<site_slug>/dashboard
# ──────────────────────────────────────────────

@portal_bp.route("/<site_slug>/dashboard")
@login_required_for_site
def dashboard(site_slug):
    """Main client dashboard — access-level-aware rendering."""
    access = g.access_level

    # No subscription yet — show subscribe page
    # But if they just came from checkout, re-check the DB fresh
    # (the webhook may have arrived between the redirect and this request)
    if access == "subscribe" and request.args.get("from") == "checkout":
        from app.models.billing import BillingSubscription
        fresh_sub = (
            BillingSubscription.query
            .filter_by(workspace_id=g.workspace_id)
            .order_by(BillingSubscription.created_at.desc())
            .first()
        )
        if fresh_sub and fresh_sub.status in ("active", "trialing"):
            g.subscription = fresh_sub
            g.access_level = "full"
            access = "full"

    if access == "subscribe":
        return render_template("portal/subscribe.html")

    # Subscription canceled/unpaid — show suspended page
    if access == "blocked":
        return render_template("portal/suspended.html")

    # Full or read_only — show dashboard
    recent_tickets = (
        Ticket.query
        .filter_by(workspace_id=g.workspace_id)
        .order_by(Ticket.last_activity_at.desc())
        .limit(5)
        .all()
    )

    # Workspace team members
    members = WorkspaceMember.query.filter_by(workspace_id=g.workspace_id).all()
    team_members = []
    for m in members:
        user = db.session.get(User, m.user_id)
        if user:
            team_members.append({"user": user, "member": m})

    return render_template(
        "portal/dashboard.html",
        recent_tickets=recent_tickets,
        team_members=team_members,
    )


# ──────────────────────────────────────────────
# TICKETS
# ──────────────────────────────────────────────

@portal_bp.route("/<site_slug>/tickets")
@login_required_for_site
def ticket_list(site_slug):
    """List all tickets for this workspace.

    Accessible at all access levels (full, read_only, blocked)
    so clients can always view existing tickets.
    """
    status_filter = request.args.get("status")
    tickets = ticket_service.list_tickets_for_workspace(
        g.workspace_id, status_filter=status_filter
    )
    return render_template(
        "portal/tickets/list.html",
        tickets=tickets,
        status_filter=status_filter,
    )


@portal_bp.route("/<site_slug>/tickets/new", methods=["GET", "POST"])
@login_required_for_site
def ticket_new(site_slug):
    """Create a new support ticket.

    Requires g.access_level == 'full'. Clients with past_due, blocked,
    or no subscription cannot create tickets.
    """
    if g.access_level != "full":
        flash("You need an active subscription to create tickets.", "warning")
        return redirect(url_for("portal.ticket_list", site_slug=site_slug))

    if request.method == "POST":
        subject = request.form.get("subject", "").strip()
        description = request.form.get("description", "").strip()
        category = request.form.get("category", "").strip() or None

        if not subject or not description:
            flash("Subject and description are required.", "error")
            return render_template(
                "portal/tickets/new.html",
                subject=subject,
                description=description,
                category=category,
            )

        try:
            ticket = ticket_service.create_ticket(
                workspace_id=g.workspace_id,
                site_id=g.site.id,
                user_id=current_user.id,
                subject=subject,
                description=description,
                category=category,
            )

            # Handle file attachments — create a system message to hold them
            uploaded_files = request.files.getlist("attachments")
            uploaded_files = [f for f in uploaded_files if f and f.filename]
            if uploaded_files:
                # Attachments on ticket creation go on an auto-created first message
                msg = ticket_service.add_message(
                    ticket_id=ticket.id,
                    user_id=current_user.id,
                    message="(attached files)",
                    is_internal=False,
                )
                ticket_service.add_attachments(ticket.id, msg.id, uploaded_files)

            db.session.commit()

            # Email notification to admin
            admin_email = current_app.config.get("MAIL_CONTACT_TO", "info@belvieudigital.com")
            base_url = current_app.config["APP_BASE_URL"]
            send_email(
                to=admin_email,
                subject=f"New ticket from {g.workspace.name}: {subject}",
                template="emails/ticket_new_notification.html",
                context={
                    "ticket_subject": subject,
                    "ticket_description": description,
                    "ticket_category": category,
                    "workspace_name": g.workspace.name,
                    "author_name": current_user.full_name,
                    "author_email": current_user.email,
                    "ticket_url": f"{base_url}/admin/tickets/{ticket.id}",
                },
                reply_to=current_user.email,
            )

            flash("Ticket created successfully.", "success")
            return redirect(
                url_for("portal.ticket_detail", site_slug=site_slug, ticket_id=ticket.id)
            )
        except ValueError as e:
            flash(str(e), "error")
            return render_template(
                "portal/tickets/new.html",
                subject=subject,
                description=description,
                category=category,
            )

    return render_template("portal/tickets/new.html")


@portal_bp.route("/<site_slug>/tickets/<ticket_id>")
@login_required_for_site
def ticket_detail(site_slug, ticket_id):
    """View a ticket and its message thread.

    Internal notes (is_internal=True) are hidden from client view.
    Only admin sees internal notes (handled in admin blueprint, Phase 6).
    """
    ticket, messages = ticket_service.get_ticket_with_messages(
        ticket_id, include_internal=False
    )

    if ticket is None or ticket.workspace_id != g.workspace_id:
        flash("Ticket not found.", "error")
        return redirect(url_for("portal.ticket_list", site_slug=site_slug))

    return render_template(
        "portal/tickets/detail.html",
        ticket=ticket,
        messages=messages,
    )


@portal_bp.route("/<site_slug>/tickets/<ticket_id>/reply", methods=["POST"])
@login_required_for_site
def ticket_reply(site_slug, ticket_id):
    """Add a reply to a ticket thread.

    Requires g.access_level == 'full'. Client replies are never internal.
    """
    if g.access_level != "full":
        flash("You need an active subscription to reply to tickets.", "warning")
        return redirect(
            url_for("portal.ticket_detail", site_slug=site_slug, ticket_id=ticket_id)
        )

    # Verify ticket belongs to this workspace
    ticket = db.session.get(Ticket, ticket_id)
    if ticket is None or ticket.workspace_id != g.workspace_id:
        flash("Ticket not found.", "error")
        return redirect(url_for("portal.ticket_list", site_slug=site_slug))

    message = request.form.get("message", "").strip()
    uploaded_files = request.files.getlist("attachments")
    uploaded_files = [f for f in uploaded_files if f and f.filename]

    if not message and not uploaded_files:
        flash("Reply cannot be empty.", "error")
        return redirect(
            url_for("portal.ticket_detail", site_slug=site_slug, ticket_id=ticket_id)
        )

    try:
        msg = ticket_service.add_message(
            ticket_id=ticket_id,
            user_id=current_user.id,
            message=message or "(attached files)",
            is_internal=False,  # client replies are never internal
        )

        if uploaded_files:
            ticket_service.add_attachments(ticket_id, msg.id, uploaded_files)

        db.session.commit()

        # Email notification to admin
        admin_email = current_app.config.get("MAIL_CONTACT_TO", "info@belvieudigital.com")
        base_url = current_app.config["APP_BASE_URL"]
        send_email(
            to=admin_email,
            subject=f"Reply from {g.workspace.name}: {ticket.subject}",
            template="emails/ticket_reply_to_admin.html",
            context={
                "ticket_subject": ticket.subject,
                "reply_message": message,
                "workspace_name": g.workspace.name,
                "author_name": current_user.full_name,
                "author_email": current_user.email,
                "ticket_url": f"{base_url}/admin/tickets/{ticket_id}",
            },
            reply_to=current_user.email,
        )

        flash("Reply added.", "success")
    except ValueError as e:
        flash(str(e), "error")

    return redirect(
        url_for("portal.ticket_detail", site_slug=site_slug, ticket_id=ticket_id)
    )
