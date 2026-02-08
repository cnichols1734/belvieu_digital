"""Auth blueprint — /auth/*

Handles invite-gated registration, login, logout.
Auth routes are slug-independent per design decision #10.
"""

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db, limiter
from app.models.audit import AuditEvent
from app.models.user import User
from app.models.workspace import WorkspaceMember
from app.services import invite_service

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


# ──────────────────────────────────────────────
# GET/POST /auth/register?token=<invite_token>
# ──────────────────────────────────────────────

@auth_bp.route("/register", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def register():
    """Invite-gated registration.

    GET: show register form (validates token first)
    POST: create user + workspace member, consume invite, log in
    """
    # Already logged in? Redirect to home
    if current_user.is_authenticated:
        return redirect("/")

    token = request.args.get("token") or request.form.get("token")

    # No token at all -> redirect to login
    if not token:
        flash("An invite link is required to register.", "error")
        return redirect(url_for("auth.login"))

    # Validate token
    invite, error = invite_service.validate_token(token)
    if error:
        flash(error, "error")
        return render_template("auth/register.html", token=token, invite_error=True)

    # Load associated site for redirect after registration
    site = invite.site

    if request.method == "POST":
        email = request.form.get("email", "").lower().strip()
        password = request.form.get("password", "")
        full_name = request.form.get("full_name", "").strip()

        # --- Validation ---
        errors = []

        if not email:
            errors.append("Email is required.")
        if not password:
            errors.append("Password is required.")
        elif len(password) < 8:
            errors.append("Password must be at least 8 characters.")
        if not full_name:
            errors.append("Full name is required.")

        # Check email-lock on invite
        if email:
            email_ok, email_error = invite_service.check_email_match(invite, email)
            if not email_ok:
                errors.append(email_error)

        # Check email uniqueness
        if email and User.query.filter_by(email=email).first():
            errors.append("An account with this email already exists.")

        # Re-validate token (could have been used between GET and POST)
        invite, token_error = invite_service.validate_token(token)
        if token_error:
            flash(token_error, "error")
            return render_template(
                "auth/register.html", token=token, invite_error=True
            )

        if errors:
            for err in errors:
                flash(err, "error")
            return render_template(
                "auth/register.html",
                token=token,
                email=email,
                full_name=full_name,
                locked_email=invite.email,
            )

        # --- Create user ---
        user = User(
            email=email,
            password_hash=generate_password_hash(password),
            full_name=full_name,
        )
        db.session.add(user)
        db.session.flush()  # get user.id

        # --- Create workspace membership ---
        # First user gets "owner", subsequent users get "member"
        existing_owner = WorkspaceMember.query.filter_by(
            workspace_id=invite.workspace_id, role="owner"
        ).first()
        role = "member" if existing_owner else "owner"

        membership = WorkspaceMember(
            user_id=user.id,
            workspace_id=invite.workspace_id,
            role=role,
        )
        db.session.add(membership)

        # --- Consume invite ---
        invite_service.consume_invite(invite)

        # --- Audit log ---
        audit = AuditEvent(
            workspace_id=invite.workspace_id,
            actor_user_id=user.id,
            action="user.registered",
            metadata_={
                "email": email,
                "invite_id": invite.id,
                "site_slug": site.site_slug,
            },
        )
        db.session.add(audit)

        db.session.commit()

        # --- Log user in ---
        login_user(user)

        flash("Welcome! Your account has been created.", "success")
        return redirect(f"/{site.site_slug}/dashboard")

    # GET — render register form
    return render_template(
        "auth/register.html",
        token=token,
        locked_email=invite.email,
    )


# ──────────────────────────────────────────────
# GET/POST /auth/login?next=/<slug>/dashboard
# ──────────────────────────────────────────────

@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("15 per minute", methods=["POST"])
def login():
    """Standard email + password login.

    After login, redirects to the `next` query param (which typically
    contains the slug path, e.g. /demo-pizza/dashboard).
    """
    if current_user.is_authenticated:
        next_url = request.args.get("next", "/")
        return redirect(next_url)

    if request.method == "POST":
        email = request.form.get("email", "").lower().strip()
        password = request.form.get("password", "")
        remember = bool(request.form.get("remember"))

        if not email or not password:
            flash("Email and password are required.", "error")
            return render_template(
                "auth/login.html",
                email=email,
                next_url=request.form.get("next", ""),
            )

        user = User.query.filter_by(email=email).first()

        if user is None or not check_password_hash(user.password_hash, password):
            flash("Invalid email or password.", "error")
            return render_template(
                "auth/login.html",
                email=email,
                next_url=request.form.get("next", ""),
            )

        if not user.is_active:
            flash("Your account has been deactivated.", "error")
            return render_template(
                "auth/login.html",
                email=email,
                next_url=request.form.get("next", ""),
            )

        login_user(user, remember=remember)

        # Redirect to `next` (from query param or hidden form field)
        next_url = request.form.get("next") or request.args.get("next", "/")

        # Safety: only allow relative redirects (prevent open redirect)
        if not next_url.startswith("/"):
            next_url = "/"

        flash("Logged in successfully.", "success")
        return redirect(next_url)

    # GET — render login form
    return render_template(
        "auth/login.html",
        next_url=request.args.get("next", ""),
    )


# ──────────────────────────────────────────────
# GET /auth/logout
# ──────────────────────────────────────────────

@auth_bp.route("/logout")
def logout():
    """Log out and redirect to login page."""
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))
