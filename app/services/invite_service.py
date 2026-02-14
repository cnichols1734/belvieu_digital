"""Invite service — token generation, validation, and consumption.

Handles the full lifecycle of workspace invite tokens:
- generate: create a new invite tied to a workspace + site
- validate: check if a token exists, is not expired, and is not used
- consume: mark an invite as used during registration
"""

import secrets
from datetime import datetime, timedelta, timezone

from app.extensions import db
from app.models.invite import WorkspaceInvite


def generate_invite(workspace_id, site_id, email=None, expires_days=45):
    """Create a new invite token for a workspace + site.

    Args:
        workspace_id: UUID of the workspace
        site_id: UUID of the site
        email: Optional email to lock the invite to
        expires_days: Number of days until the token expires (default 45)

    Returns:
        WorkspaceInvite: the newly created invite row
    """
    token = secrets.token_urlsafe(48)  # produces ~64-char base64 string
    invite = WorkspaceInvite(
        workspace_id=workspace_id,
        site_id=site_id,
        email=email.lower().strip() if email else None,
        token=token,
        expires_at=datetime.now(timezone.utc) + timedelta(days=expires_days),
    )
    db.session.add(invite)
    db.session.commit()
    return invite


def validate_token(token):
    """Look up an invite token and check if it's usable.

    Args:
        token: The invite token string from the URL

    Returns:
        tuple: (invite, error_message)
            - If valid: (WorkspaceInvite, None)
            - If invalid: (None, "reason string")
    """
    if not token:
        return None, "No invite token provided."

    invite = WorkspaceInvite.query.filter_by(token=token).first()

    if invite is None:
        return None, "Invalid invite link."

    if invite.is_used:
        return None, "This invite link has already been used."

    if invite.is_expired:
        return None, "This invite link has expired."

    return invite, None


def check_email_match(invite, email):
    """If the invite is locked to an email, verify it matches.

    Args:
        invite: WorkspaceInvite row
        email: The email the user is trying to register with

    Returns:
        tuple: (ok, error_message)
            - If ok: (True, None)
            - If mismatch: (False, "reason string")
    """
    if invite.email is None:
        # Invite is not email-locked — any email is fine
        return True, None

    if email.lower().strip() == invite.email.lower().strip():
        return True, None

    return False, "This invite is reserved for a different email address."


def consume_invite(invite):
    """Mark an invite as used (set used_at timestamp).

    Should be called after the user is successfully created and
    the workspace membership is established.

    Args:
        invite: WorkspaceInvite row to consume
    """
    invite.used_at = datetime.now(timezone.utc)
    db.session.add(invite)
    # Don't commit here — caller should commit as part of the
    # larger registration transaction
