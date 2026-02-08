"""
Custom route decorators for access control.

- login_required_for_site: ensures user is logged in AND is a member of the
  workspace resolved from the current site_slug (dual tenant check).
- admin_required: ensures user is logged in AND has is_admin=True.
"""

from functools import wraps

from flask import abort, g
from flask_login import current_user, login_required


def login_required_for_site(f):
    """Require login + workspace membership for the current site_slug."""

    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        # g.workspace_id is set by tenant middleware
        if not hasattr(g, "workspace_id") or g.workspace_id is None:
            abort(404)

        # Dual check: verify membership exists (imported lazily to avoid
        # circular imports -- models aren't defined yet in Phase 0)
        from app.models.workspace import WorkspaceMember

        membership = WorkspaceMember.query.filter_by(
            user_id=current_user.id,
            workspace_id=g.workspace_id,
        ).first()

        if membership is None:
            abort(403)

        return f(*args, **kwargs)

    return decorated


def admin_required(f):
    """Require login + is_admin flag."""

    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)

    return decorated
