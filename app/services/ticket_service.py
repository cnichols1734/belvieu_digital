"""Ticket service — CRUD, status machine, assignment, internal notes.

All ticket content (subject, description, messages) is sanitized with
bleach.clean() to strip HTML tags. Status transitions are enforced via
Ticket.VALID_TRANSITIONS dict.

Functions flush but do NOT commit — the caller commits.
"""

import bleach
from datetime import datetime, timezone

from app.extensions import db
from app.models.ticket import Ticket, TicketMessage
from app.models.audit import AuditEvent


def _sanitize(text):
    """Strip all HTML tags from user input."""
    if text is None:
        return text
    return bleach.clean(text, tags=[], strip=True).strip()


def create_ticket(workspace_id, site_id, user_id, subject, description, category=None):
    """Create a new support ticket.

    Args:
        workspace_id: Workspace UUID string.
        site_id: Site UUID string.
        user_id: Author's user UUID string.
        subject: Ticket subject (will be sanitized).
        description: Ticket description (will be sanitized).
        category: One of Ticket.CATEGORIES or None.

    Returns:
        The created Ticket object.

    Raises:
        ValueError: If category is invalid.
    """
    subject = _sanitize(subject)
    description = _sanitize(description)

    if not subject:
        raise ValueError("Subject is required.")
    if not description:
        raise ValueError("Description is required.")

    if category and category not in Ticket.CATEGORIES:
        raise ValueError(
            f"Invalid category '{category}'. Must be one of: {', '.join(Ticket.CATEGORIES)}"
        )

    now = datetime.now(timezone.utc)

    ticket = Ticket(
        workspace_id=workspace_id,
        site_id=site_id,
        author_user_id=user_id,
        subject=subject,
        description=description,
        category=category,
        status="open",
        priority="normal",
        last_activity_at=now,
    )
    db.session.add(ticket)
    db.session.flush()

    # Audit log
    audit = AuditEvent(
        workspace_id=workspace_id,
        actor_user_id=user_id,
        action="ticket.created",
        metadata_={
            "ticket_id": ticket.id,
            "subject": subject,
            "category": category,
        },
    )
    db.session.add(audit)
    db.session.flush()

    return ticket


def add_message(ticket_id, user_id, message, is_internal=False):
    """Add a message to a ticket's thread.

    Args:
        ticket_id: Ticket UUID string.
        user_id: Author's user UUID string.
        message: Message body (will be sanitized).
        is_internal: If True, only visible to admins.

    Returns:
        The created TicketMessage object.

    Raises:
        ValueError: If ticket not found or message is empty.
    """
    message_text = _sanitize(message)
    if not message_text:
        raise ValueError("Message cannot be empty.")

    ticket = db.session.get(Ticket, ticket_id)
    if ticket is None:
        raise ValueError(f"Ticket {ticket_id} not found.")

    now = datetime.now(timezone.utc)

    msg = TicketMessage(
        ticket_id=ticket_id,
        author_user_id=user_id,
        message=message_text,
        is_internal=bool(is_internal),
    )
    db.session.add(msg)

    # Update ticket activity timestamp
    ticket.last_activity_at = now
    ticket.updated_at = now

    # Auto-transition: if ticket is waiting_on_client and the reply is
    # from a non-internal user (client), move to in_progress
    from app.models.user import User
    author = db.session.get(User, user_id)
    if (
        ticket.status == "waiting_on_client"
        and not is_internal
        and author is not None
        and not author.is_admin
    ):
        ticket.status = "in_progress"

    db.session.flush()

    # Audit log
    audit = AuditEvent(
        workspace_id=ticket.workspace_id,
        actor_user_id=user_id,
        action="ticket.message_added",
        metadata_={
            "ticket_id": ticket_id,
            "is_internal": is_internal,
        },
    )
    db.session.add(audit)
    db.session.flush()

    return msg


def update_status(ticket_id, new_status, actor_user_id):
    """Change a ticket's status, enforcing valid transitions.

    Args:
        ticket_id: Ticket UUID string.
        new_status: Target status string.
        actor_user_id: User performing the change.

    Returns:
        The updated Ticket.

    Raises:
        ValueError: If ticket not found, status invalid, or transition not allowed.
    """
    ticket = db.session.get(Ticket, ticket_id)
    if ticket is None:
        raise ValueError(f"Ticket {ticket_id} not found.")

    if new_status not in Ticket.STATUSES:
        raise ValueError(
            f"Invalid status '{new_status}'. Must be one of: {', '.join(Ticket.STATUSES)}"
        )

    old_status = ticket.status

    if old_status == new_status:
        return ticket  # no-op

    # Check valid transitions
    allowed = Ticket.VALID_TRANSITIONS.get(old_status, [])
    if new_status not in allowed:
        raise ValueError(
            f"Cannot transition from '{old_status}' to '{new_status}'. "
            f"Allowed: {', '.join(allowed) if allowed else 'none (terminal state)'}"
        )

    now = datetime.now(timezone.utc)
    ticket.status = new_status
    ticket.last_activity_at = now
    ticket.updated_at = now
    db.session.flush()

    # Audit log
    audit = AuditEvent(
        workspace_id=ticket.workspace_id,
        actor_user_id=actor_user_id,
        action="ticket.status_changed",
        metadata_={
            "ticket_id": ticket_id,
            "old_status": old_status,
            "new_status": new_status,
        },
    )
    db.session.add(audit)
    db.session.flush()

    return ticket


def assign_ticket(ticket_id, assigned_to_user_id, actor_user_id):
    """Assign a ticket to an admin user.

    Args:
        ticket_id: Ticket UUID string.
        assigned_to_user_id: User UUID to assign to (must be admin), or None to unassign.
        actor_user_id: User performing the assignment.

    Returns:
        The updated Ticket.

    Raises:
        ValueError: If ticket not found or assignee is not admin.
    """
    ticket = db.session.get(Ticket, ticket_id)
    if ticket is None:
        raise ValueError(f"Ticket {ticket_id} not found.")

    if assigned_to_user_id is not None:
        from app.models.user import User
        assignee = db.session.get(User, assigned_to_user_id)
        if assignee is None:
            raise ValueError("Assignee user not found.")
        if not assignee.is_admin:
            raise ValueError("Tickets can only be assigned to admin users.")

    old_assignee = ticket.assigned_to_user_id
    ticket.assigned_to_user_id = assigned_to_user_id

    now = datetime.now(timezone.utc)
    ticket.last_activity_at = now
    ticket.updated_at = now
    db.session.flush()

    # Audit log
    audit = AuditEvent(
        workspace_id=ticket.workspace_id,
        actor_user_id=actor_user_id,
        action="ticket.assigned",
        metadata_={
            "ticket_id": ticket_id,
            "old_assignee": old_assignee,
            "new_assignee": assigned_to_user_id,
        },
    )
    db.session.add(audit)
    db.session.flush()

    return ticket


def get_ticket_with_messages(ticket_id, include_internal=False):
    """Load a ticket and its messages.

    Args:
        ticket_id: Ticket UUID string.
        include_internal: If True, include internal notes. False for client view.

    Returns:
        Tuple of (ticket, messages_list) or (None, []) if not found.
    """
    ticket = db.session.get(Ticket, ticket_id)
    if ticket is None:
        return None, []

    query = TicketMessage.query.filter_by(ticket_id=ticket_id)
    if not include_internal:
        query = query.filter_by(is_internal=False)
    messages = query.order_by(TicketMessage.created_at.asc()).all()

    return ticket, messages


def get_monthly_edit_usage(workspace_id):
    """Count completed content_update tickets for the current calendar month.

    Returns:
        dict with keys:
            used  – number of content_update tickets marked done this month
            limit – monthly allowance (None = unlimited)
    """
    from app.models.workspace import Workspace, WorkspaceSettings

    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    used = (
        Ticket.query
        .filter(
            Ticket.workspace_id == workspace_id,
            Ticket.category == "content_update",
            Ticket.status == "done",
            Ticket.updated_at >= month_start,
        )
        .count()
    )

    # Get the workspace's update allowance
    settings = WorkspaceSettings.query.filter_by(workspace_id=workspace_id).first()
    limit = settings.update_allowance if settings else None

    return {"used": used, "limit": limit}


def get_monthly_edit_usage_bulk(workspace_ids):
    """Count completed content_update tickets for multiple workspaces in the current month.

    Returns:
        dict mapping workspace_id -> {"used": int, "limit": int|None}
    """
    from app.models.workspace import WorkspaceSettings

    if not workspace_ids:
        return {}

    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Count done content_update tickets per workspace this month
    from sqlalchemy import func
    rows = (
        db.session.query(Ticket.workspace_id, func.count(Ticket.id))
        .filter(
            Ticket.workspace_id.in_(workspace_ids),
            Ticket.category == "content_update",
            Ticket.status == "done",
            Ticket.updated_at >= month_start,
        )
        .group_by(Ticket.workspace_id)
        .all()
    )
    usage_map = {ws_id: count for ws_id, count in rows}

    # Get allowances
    settings_rows = (
        WorkspaceSettings.query
        .filter(WorkspaceSettings.workspace_id.in_(workspace_ids))
        .all()
    )
    allowance_map = {s.workspace_id: s.update_allowance for s in settings_rows}

    result = {}
    for ws_id in workspace_ids:
        result[ws_id] = {
            "used": usage_map.get(ws_id, 0),
            "limit": allowance_map.get(ws_id),
        }
    return result


def update_category(ticket_id, new_category, actor_user_id):
    """Change a ticket's category.

    Args:
        ticket_id: Ticket UUID string.
        new_category: New category string (must be in Ticket.CATEGORIES) or None.
        actor_user_id: User performing the change.

    Returns:
        The updated Ticket.

    Raises:
        ValueError: If ticket not found or category invalid.
    """
    ticket = db.session.get(Ticket, ticket_id)
    if ticket is None:
        raise ValueError(f"Ticket {ticket_id} not found.")

    if new_category and new_category not in Ticket.CATEGORIES:
        raise ValueError(
            f"Invalid category '{new_category}'. "
            f"Must be one of: {', '.join(Ticket.CATEGORIES)}"
        )

    old_category = ticket.category
    ticket.category = new_category or None

    now = datetime.now(timezone.utc)
    ticket.updated_at = now
    db.session.flush()

    # Audit log
    audit = AuditEvent(
        workspace_id=ticket.workspace_id,
        actor_user_id=actor_user_id,
        action="ticket.category_changed",
        metadata_={
            "ticket_id": ticket_id,
            "old_category": old_category,
            "new_category": new_category,
        },
    )
    db.session.add(audit)
    db.session.flush()

    return ticket


def list_tickets_for_workspace(workspace_id, status_filter=None):
    """List tickets for a workspace, optionally filtered by status.

    Args:
        workspace_id: Workspace UUID string.
        status_filter: Optional status string to filter by.

    Returns:
        List of Ticket objects, ordered by last_activity_at desc.
    """
    query = Ticket.query.filter_by(workspace_id=workspace_id)
    if status_filter and status_filter in Ticket.STATUSES:
        query = query.filter_by(status=status_filter)
    return query.order_by(Ticket.last_activity_at.desc()).all()
