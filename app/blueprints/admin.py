"""Admin blueprint — /admin/*

Prospect pipeline (lite CRM), workspace management, ticket management.
All routes protected by @admin_required decorator.

Route Map:
  GET  /admin/                              — Dashboard overview
  GET  /admin/prospects                     — Pipeline list
  GET/POST /admin/prospects/new             — Add new prospect
  GET  /admin/prospects/<id>                — Prospect detail
  POST /admin/prospects/<id>                — Update prospect
  POST /admin/prospects/<id>/convert        — Convert prospect to client
  GET  /admin/workspaces                    — Workspace list
  GET  /admin/workspaces/<id>               — Workspace detail
  POST /admin/workspaces/<id>/invite        — Generate invite link
  GET  /admin/tickets                       — All tickets cross-workspace
  GET  /admin/tickets/<id>                  — Ticket detail + admin controls
  POST /admin/tickets/<id>/reply            — Admin reply (with internal notes)
  POST /admin/tickets/<id>/status           — Change ticket status
  POST /admin/tickets/<id>/assign           — Assign ticket
  POST /admin/sites/<id>/status             — Override site status
"""

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user

from app.decorators import admin_required
from app.extensions import db
from app.models.audit import AuditEvent
from app.models.billing import BillingCustomer, BillingSubscription
from app.models.invite import WorkspaceInvite
from app.models.prospect import Prospect
from app.models.site import Site
from app.models.ticket import Ticket, TicketMessage
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember, WorkspaceSettings
from app.services import invite_service, ticket_service

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


# ══════════════════════════════════════════════
#  DASHBOARD
# ══════════════════════════════════════════════

@admin_bp.route("/")
@admin_required
def dashboard():
    """Admin dashboard — overview metrics, pipeline summary, open tickets, activity feed."""

    # --- Pipeline counts ---
    pipeline_counts = {}
    for status in Prospect.STATUSES:
        pipeline_counts[status] = Prospect.query.filter_by(status=status).count()
    total_prospects = sum(pipeline_counts.values())

    # --- Conversion rate ---
    pitched = pipeline_counts.get("pitched", 0)
    converted = pipeline_counts.get("converted", 0)
    conversion_denominator = pitched + converted + pipeline_counts.get("declined", 0)
    conversion_rate = (
        round((converted / conversion_denominator) * 100)
        if conversion_denominator > 0
        else 0
    )

    # --- Revenue metrics ---
    active_subs = BillingSubscription.query.filter_by(status="active").all()
    active_count = len(active_subs)
    mrr = 0
    for sub in active_subs:
        if sub.plan == "basic":
            mrr += 59
        elif sub.plan == "pro":
            mrr += 99

    # --- Open tickets ---
    open_tickets_count = Ticket.query.filter(
        Ticket.status.in_(["open", "in_progress", "waiting_on_client"])
    ).count()

    # --- Pending invites ---
    from datetime import datetime, timezone

    pending_invites = WorkspaceInvite.query.filter(
        WorkspaceInvite.used_at.is_(None),
        WorkspaceInvite.expires_at > datetime.now(timezone.utc),
    ).count()

    # --- Recent activity ---
    recent_activity = (
        AuditEvent.query
        .order_by(AuditEvent.created_at.desc())
        .limit(20)
        .all()
    )

    return render_template(
        "admin/dashboard.html",
        pipeline_counts=pipeline_counts,
        total_prospects=total_prospects,
        conversion_rate=conversion_rate,
        active_count=active_count,
        mrr=mrr,
        open_tickets_count=open_tickets_count,
        pending_invites=pending_invites,
        recent_activity=recent_activity,
    )


# ══════════════════════════════════════════════
#  PROSPECTS (Lite CRM)
# ══════════════════════════════════════════════

@admin_bp.route("/prospects")
@admin_required
def prospect_list():
    """Pipeline view: all prospects, filterable by status."""
    status_filter = request.args.get("status")
    query = Prospect.query

    if status_filter and status_filter in Prospect.STATUSES:
        query = query.filter_by(status=status_filter)

    prospects = query.order_by(Prospect.updated_at.desc()).all()

    return render_template(
        "admin/prospects.html",
        prospects=prospects,
        status_filter=status_filter,
        statuses=Prospect.STATUSES,
    )


@admin_bp.route("/prospects/new", methods=["GET", "POST"])
@admin_required
def prospect_new():
    """Add a new prospect from Google Maps / Facebook find."""
    if request.method == "POST":
        business_name = request.form.get("business_name", "").strip()
        contact_name = request.form.get("contact_name", "").strip() or None
        contact_email = request.form.get("contact_email", "").strip() or None
        contact_phone = request.form.get("contact_phone", "").strip() or None
        source = request.form.get("source", "").strip()
        source_url = request.form.get("source_url", "").strip() or None
        notes = request.form.get("notes", "").strip() or None
        demo_url = request.form.get("demo_url", "").strip() or None

        if not business_name:
            flash("Business name is required.", "error")
            return render_template("admin/prospect_new.html",
                                   form_data=request.form)

        if source not in ["google_maps", "facebook", "referral", "other"]:
            flash("Please select a valid source.", "error")
            return render_template("admin/prospect_new.html",
                                   form_data=request.form)

        prospect = Prospect(
            business_name=business_name,
            contact_name=contact_name,
            contact_email=contact_email,
            contact_phone=contact_phone,
            source=source,
            source_url=source_url,
            notes=notes,
            demo_url=demo_url,
            status="researching",
        )
        db.session.add(prospect)

        # Audit log
        audit = AuditEvent(
            actor_user_id=current_user.id,
            action="prospect.created",
            metadata_={
                "business_name": business_name,
                "source": source,
            },
        )
        db.session.add(audit)
        db.session.commit()

        flash(f"Prospect '{business_name}' created.", "success")
        return redirect(url_for("admin.prospect_detail", prospect_id=prospect.id))

    return render_template("admin/prospect_new.html", form_data={})


@admin_bp.route("/prospects/<prospect_id>", methods=["GET"])
@admin_required
def prospect_detail(prospect_id):
    """Prospect detail: info, notes, status, demo URL."""
    prospect = db.session.get(Prospect, prospect_id)
    if prospect is None:
        flash("Prospect not found.", "error")
        return redirect(url_for("admin.prospect_list"))

    return render_template("admin/prospect_detail.html", prospect=prospect)


@admin_bp.route("/prospects/<prospect_id>/update", methods=["POST"])
@admin_required
def prospect_update(prospect_id):
    """Update prospect info, notes, status, demo URL."""
    prospect = db.session.get(Prospect, prospect_id)
    if prospect is None:
        flash("Prospect not found.", "error")
        return redirect(url_for("admin.prospect_list"))

    # Update fields
    prospect.business_name = request.form.get("business_name", prospect.business_name).strip()
    prospect.contact_name = request.form.get("contact_name", "").strip() or None
    prospect.contact_email = request.form.get("contact_email", "").strip() or None
    prospect.contact_phone = request.form.get("contact_phone", "").strip() or None
    prospect.source = request.form.get("source", prospect.source).strip()
    prospect.source_url = request.form.get("source_url", "").strip() or None
    prospect.notes = request.form.get("notes", "").strip() or None
    prospect.demo_url = request.form.get("demo_url", "").strip() or None

    # Status change
    new_status = request.form.get("status", "").strip()
    if new_status and new_status in Prospect.STATUSES and new_status != prospect.status:
        old_status = prospect.status
        prospect.status = new_status

        audit = AuditEvent(
            actor_user_id=current_user.id,
            action="prospect.status_changed",
            metadata_={
                "prospect_id": prospect_id,
                "old_status": old_status,
                "new_status": new_status,
            },
        )
        db.session.add(audit)

    db.session.commit()
    flash("Prospect updated.", "success")
    return redirect(url_for("admin.prospect_detail", prospect_id=prospect_id))


@admin_bp.route("/prospects/<prospect_id>/convert", methods=["GET", "POST"])
@admin_required
def prospect_convert(prospect_id):
    """Convert prospect to client — creates workspace + site + settings + invite.

    GET  — show conversion form pre-filled from prospect
    POST — execute the conversion
    """
    prospect = db.session.get(Prospect, prospect_id)
    if prospect is None:
        flash("Prospect not found.", "error")
        return redirect(url_for("admin.prospect_list"))

    if prospect.status == "converted":
        flash("This prospect has already been converted.", "warning")
        return redirect(url_for("admin.prospect_detail", prospect_id=prospect_id))

    if request.method == "POST":
        site_slug = request.form.get("site_slug", "").strip().lower()
        display_name = request.form.get("display_name", "").strip()
        published_url = request.form.get("published_url", "").strip() or None
        custom_domain = request.form.get("custom_domain", "").strip() or None
        invite_email = request.form.get("invite_email", "").strip() or None

        # Validation
        if not site_slug:
            flash("Site slug is required.", "error")
            return render_template("admin/workspace_convert.html",
                                   prospect=prospect, form_data=request.form)

        # Check slug uniqueness
        existing_site = Site.query.filter_by(site_slug=site_slug).first()
        if existing_site:
            flash(f"Site slug '{site_slug}' is already taken.", "error")
            return render_template("admin/workspace_convert.html",
                                   prospect=prospect, form_data=request.form)

        if not display_name:
            display_name = prospect.business_name

        # 1. Create workspace
        workspace = Workspace(
            name=prospect.business_name,
            prospect_id=prospect.id,
        )
        db.session.add(workspace)
        db.session.flush()

        # 2. Create workspace settings
        settings = WorkspaceSettings(workspace_id=workspace.id)
        db.session.add(settings)

        # 3. Create site
        site = Site(
            workspace_id=workspace.id,
            site_slug=site_slug,
            display_name=display_name,
            published_url=published_url or prospect.demo_url,
            custom_domain=custom_domain,
            status="demo",
        )
        db.session.add(site)
        db.session.flush()

        # 4. Create invite
        invite = invite_service.generate_invite(
            workspace_id=workspace.id,
            site_id=site.id,
            email=invite_email,
        )
        # generate_invite commits, but we need to continue the transaction
        # so we flush the rest. Actually generate_invite already committed,
        # which is fine — the workspace/settings/site are already flushed.

        # 5. Update prospect
        prospect.status = "converted"
        prospect.workspace_id = workspace.id

        # 6. Audit log
        audit = AuditEvent(
            actor_user_id=current_user.id,
            action="prospect.converted",
            metadata_={
                "prospect_id": prospect_id,
                "workspace_id": workspace.id,
                "site_id": site.id,
                "site_slug": site_slug,
            },
        )
        db.session.add(audit)
        db.session.commit()

        # Build the invite link
        base_url = current_app.config.get("APP_BASE_URL", "http://localhost:5000")
        invite_link = f"{base_url}/auth/register?token={invite.token}"

        flash("Prospect converted to client successfully!", "success")
        return render_template(
            "admin/workspace_convert_success.html",
            prospect=prospect,
            workspace=workspace,
            site=site,
            invite=invite,
            invite_link=invite_link,
        )

    return render_template("admin/workspace_convert.html",
                           prospect=prospect, form_data={})


# ══════════════════════════════════════════════
#  WORKSPACES
# ══════════════════════════════════════════════

@admin_bp.route("/workspaces")
@admin_required
def workspace_list():
    """List all workspaces with subscription status and invite info."""
    workspaces = Workspace.query.order_by(Workspace.created_at.desc()).all()

    # Build enriched data for each workspace
    workspace_data = []
    for ws in workspaces:
        site = ws.sites.first()
        sub = (
            BillingSubscription.query
            .filter_by(workspace_id=ws.id)
            .order_by(BillingSubscription.created_at.desc())
            .first()
        )
        # Latest invite
        latest_invite = (
            WorkspaceInvite.query
            .filter_by(workspace_id=ws.id)
            .order_by(WorkspaceInvite.created_at.desc())
            .first()
        )
        workspace_data.append({
            "workspace": ws,
            "site": site,
            "subscription": sub,
            "latest_invite": latest_invite,
        })

    return render_template("admin/workspaces.html", workspace_data=workspace_data)


@admin_bp.route("/workspaces/<workspace_id>")
@admin_required
def workspace_detail(workspace_id):
    """Full workspace detail: site, members, billing, tickets, invites."""
    workspace = db.session.get(Workspace, workspace_id)
    if workspace is None:
        flash("Workspace not found.", "error")
        return redirect(url_for("admin.workspace_list"))

    site = workspace.sites.first()
    members = workspace.members.all()

    # Enrich members with user info
    member_data = []
    for m in members:
        user = db.session.get(User, m.user_id)
        member_data.append({"member": m, "user": user})

    # Subscription
    subscription = (
        BillingSubscription.query
        .filter_by(workspace_id=workspace_id)
        .order_by(BillingSubscription.created_at.desc())
        .first()
    )

    # Billing customer
    billing_customer = BillingCustomer.query.filter_by(workspace_id=workspace_id).first()

    # Invites
    invites = (
        WorkspaceInvite.query
        .filter_by(workspace_id=workspace_id)
        .order_by(WorkspaceInvite.created_at.desc())
        .all()
    )

    # Tickets
    tickets = (
        Ticket.query
        .filter_by(workspace_id=workspace_id)
        .order_by(Ticket.last_activity_at.desc())
        .limit(10)
        .all()
    )

    # Prospect back-reference
    prospect = None
    if workspace.prospect_id:
        prospect = db.session.get(Prospect, workspace.prospect_id)

    return render_template(
        "admin/workspace_detail.html",
        workspace=workspace,
        site=site,
        member_data=member_data,
        subscription=subscription,
        billing_customer=billing_customer,
        invites=invites,
        tickets=tickets,
        prospect=prospect,
        settings=workspace.settings,
    )


@admin_bp.route("/workspaces/<workspace_id>/invite", methods=["POST"])
@admin_required
def workspace_invite(workspace_id):
    """Generate a new invite link for this workspace."""
    workspace = db.session.get(Workspace, workspace_id)
    if workspace is None:
        flash("Workspace not found.", "error")
        return redirect(url_for("admin.workspace_list"))

    site = workspace.sites.first()
    if site is None:
        flash("Workspace has no site. Cannot generate invite.", "error")
        return redirect(url_for("admin.workspace_detail", workspace_id=workspace_id))

    invite_email = request.form.get("invite_email", "").strip() or None

    invite = invite_service.generate_invite(
        workspace_id=workspace.id,
        site_id=site.id,
        email=invite_email,
    )

    # Audit log
    audit = AuditEvent(
        workspace_id=workspace.id,
        actor_user_id=current_user.id,
        action="invite.generated",
        metadata_={
            "invite_id": invite.id,
            "email": invite_email,
        },
    )
    db.session.add(audit)
    db.session.commit()

    base_url = current_app.config.get("APP_BASE_URL", "http://localhost:5000")
    invite_link = f"{base_url}/auth/register?token={invite.token}"

    flash(f"Invite link generated!", "success")
    return render_template(
        "admin/workspace_invite_success.html",
        workspace=workspace,
        invite=invite,
        invite_link=invite_link,
    )


# ══════════════════════════════════════════════
#  TICKETS (Admin view)
# ══════════════════════════════════════════════

@admin_bp.route("/tickets")
@admin_required
def ticket_list():
    """All tickets across workspaces with filters."""
    status_filter = request.args.get("status")
    assignee_filter = request.args.get("assignee")

    query = Ticket.query

    if status_filter and status_filter in Ticket.STATUSES:
        query = query.filter_by(status=status_filter)

    if assignee_filter:
        if assignee_filter == "unassigned":
            query = query.filter(Ticket.assigned_to_user_id.is_(None))
        else:
            query = query.filter_by(assigned_to_user_id=assignee_filter)

    tickets = query.order_by(Ticket.last_activity_at.desc()).all()

    # Get admin users for assignee dropdown
    admin_users = User.query.filter_by(is_admin=True).all()

    return render_template(
        "admin/tickets.html",
        tickets=tickets,
        status_filter=status_filter,
        assignee_filter=assignee_filter,
        admin_users=admin_users,
    )


@admin_bp.route("/tickets/<ticket_id>")
@admin_required
def ticket_detail(ticket_id):
    """Ticket detail with full thread (including internal notes) + admin controls."""
    ticket, messages = ticket_service.get_ticket_with_messages(
        ticket_id, include_internal=True
    )

    if ticket is None:
        flash("Ticket not found.", "error")
        return redirect(url_for("admin.ticket_list"))

    # Get admin users for assignment dropdown
    admin_users = User.query.filter_by(is_admin=True).all()

    # Get workspace + site info
    workspace = db.session.get(Workspace, ticket.workspace_id)
    site = db.session.get(Site, ticket.site_id)

    return render_template(
        "admin/ticket_detail.html",
        ticket=ticket,
        messages=messages,
        admin_users=admin_users,
        workspace=workspace,
        site=site,
    )


@admin_bp.route("/tickets/<ticket_id>/reply", methods=["POST"])
@admin_required
def ticket_reply(ticket_id):
    """Admin reply with optional internal note checkbox."""
    ticket = db.session.get(Ticket, ticket_id)
    if ticket is None:
        flash("Ticket not found.", "error")
        return redirect(url_for("admin.ticket_list"))

    message = request.form.get("message", "").strip()
    is_internal = request.form.get("is_internal") == "on"

    if not message:
        flash("Reply cannot be empty.", "error")
        return redirect(url_for("admin.ticket_detail", ticket_id=ticket_id))

    try:
        ticket_service.add_message(
            ticket_id=ticket_id,
            user_id=current_user.id,
            message=message,
            is_internal=is_internal,
        )
        db.session.commit()
        if is_internal:
            flash("Internal note added.", "success")
        else:
            flash("Reply sent.", "success")
    except ValueError as e:
        flash(str(e), "error")

    return redirect(url_for("admin.ticket_detail", ticket_id=ticket_id))


@admin_bp.route("/tickets/<ticket_id>/status", methods=["POST"])
@admin_required
def ticket_status(ticket_id):
    """Change ticket status."""
    new_status = request.form.get("status", "").strip()
    if not new_status:
        flash("Status is required.", "error")
        return redirect(url_for("admin.ticket_detail", ticket_id=ticket_id))

    try:
        ticket_service.update_status(ticket_id, new_status, current_user.id)
        db.session.commit()
        flash(f"Status changed to '{new_status}'.", "success")
    except ValueError as e:
        flash(str(e), "error")

    return redirect(url_for("admin.ticket_detail", ticket_id=ticket_id))


@admin_bp.route("/tickets/<ticket_id>/assign", methods=["POST"])
@admin_required
def ticket_assign(ticket_id):
    """Assign ticket to an admin user."""
    assigned_to = request.form.get("assigned_to", "").strip() or None

    try:
        ticket_service.assign_ticket(ticket_id, assigned_to, current_user.id)
        db.session.commit()
        if assigned_to:
            assignee = db.session.get(User, assigned_to)
            flash(f"Ticket assigned to {assignee.full_name or assignee.email}.", "success")
        else:
            flash("Ticket unassigned.", "success")
    except ValueError as e:
        flash(str(e), "error")

    return redirect(url_for("admin.ticket_detail", ticket_id=ticket_id))


# ══════════════════════════════════════════════
#  SITE STATUS OVERRIDE
# ══════════════════════════════════════════════

@admin_bp.route("/sites/<site_id>/status", methods=["POST"])
@admin_required
def site_status_override(site_id):
    """Manually override site status."""
    site = db.session.get(Site, site_id)
    if site is None:
        flash("Site not found.", "error")
        return redirect(url_for("admin.workspace_list"))

    new_status = request.form.get("status", "").strip()
    if new_status not in Site.STATUSES:
        flash(f"Invalid site status '{new_status}'.", "error")
        return redirect(url_for("admin.workspace_detail", workspace_id=site.workspace_id))

    old_status = site.status
    site.status = new_status

    audit = AuditEvent(
        workspace_id=site.workspace_id,
        actor_user_id=current_user.id,
        action="site.status_overridden",
        metadata_={
            "site_id": site_id,
            "old_status": old_status,
            "new_status": new_status,
        },
    )
    db.session.add(audit)
    db.session.commit()

    flash(f"Site status changed to '{new_status}'.", "success")
    return redirect(url_for("admin.workspace_detail", workspace_id=site.workspace_id))
