import os
import logging

import click
from flask import Flask, redirect, render_template, url_for
from flask_login import current_user
from werkzeug.security import generate_password_hash

from app.config import config_by_name
from app.extensions import db, migrate, login_manager, csrf, limiter


def create_app(config_name=None):
    """Application factory."""

    if config_name is None:
        config_name = os.environ.get("FLASK_ENV", "development")

    app = Flask(__name__)
    app.config.from_object(config_by_name[config_name])

    # --- Validate required env vars (skip in testing) ---
    if config_name != "testing":
        try:
            config_by_name[config_name].validate()
        except RuntimeError as e:
            app.logger.warning(f"Config validation: {e}")

    # --- Init extensions ---
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    # --- Import models so Alembic can discover them ---
    with app.app_context():
        from app import models  # noqa: F401

    # --- Tenant middleware ---
    from app.middleware.tenant import init_tenant_middleware
    init_tenant_middleware(app)

    # --- Register blueprints ---
    from app.blueprints.auth import auth_bp
    from app.blueprints.portal import portal_bp
    from app.blueprints.billing import billing_bp
    from app.blueprints.admin import admin_bp
    from app.blueprints.webhooks import webhooks_bp
    from app.blueprints.contact import contact_bp
    from app.blueprints.form_relay import form_relay_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(portal_bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(webhooks_bp)
    app.register_blueprint(contact_bp)
    app.register_blueprint(form_relay_bp)

    # Exempt webhooks from CSRF — raw body needed for Stripe signature verification
    csrf.exempt(webhooks_bp)
    # Exempt form relay from CSRF — public API hit by external client websites
    csrf.exempt(form_relay_bp)

    # --- Root route ---
    @app.route("/")
    def index():
        """Root URL — landing page for visitors, redirect for logged-in users."""
        if current_user.is_authenticated:
            if current_user.is_admin:
                return redirect(url_for("admin.dashboard"))
            # For regular users, find their site and redirect to portal
            from app.models.workspace import WorkspaceMember
            from app.models.site import Site
            membership = WorkspaceMember.query.filter_by(
                user_id=current_user.id
            ).first()
            if membership:
                site = Site.query.filter_by(
                    workspace_id=membership.workspace_id
                ).first()
                if site:
                    return redirect(url_for(
                        "portal.dashboard", site_slug=site.site_slug
                    ))
        return render_template("landing.html")

    # --- Local file serving (dev only) ---
    if app.debug:
        @app.route("/uploads/<path:filepath>")
        def serve_upload(filepath):
            """Serve uploaded files from instance/uploads in dev mode."""
            import os
            from flask import send_from_directory
            upload_dir = os.path.join(app.instance_path, "uploads")
            return send_from_directory(upload_dir, filepath)

    # --- Error handlers ---
    @app.errorhandler(403)
    def forbidden(e):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template("errors/500.html"), 500

    # --- CLI commands ---
    register_cli(app)

    # --- Security headers ---
    @app.after_request
    def add_security_headers(response):
        """Add security headers to every response."""
        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"
        # Control referrer information
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Prevent XSS (legacy but still useful)
        response.headers["X-XSS-Protection"] = "1; mode=block"
        # Permissions Policy (restrict browser features)
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=(self)"
        )
        # Content Security Policy
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://js.stripe.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "img-src 'self' data: https://api.microlink.io https://*.supabase.co; "
            "font-src 'self' https://fonts.gstatic.com; "
            "connect-src 'self' https://api.stripe.com; "
            "frame-src https://js.stripe.com https://hooks.stripe.com; "
            "base-uri 'self'; "
            "form-action 'self' https://checkout.stripe.com https://billing.stripe.com; "
            "frame-ancestors 'none';"
        )
        # Strict Transport Security (only in production)
        if not app.debug:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response

    # --- Custom Jinja filters ---
    import re

    @app.template_filter("slugify")
    def slugify_filter(value):
        """Convert a string to a URL-safe slug: lowercase, only a-z 0-9 and hyphens."""
        value = (value or "").lower()
        value = re.sub(r"[^a-z0-9\s-]", "", value)   # strip non-alphanumeric
        value = re.sub(r"[\s-]+", "-", value)          # collapse whitespace/hyphens
        return value.strip("-")

    # --- Logging ---
    if not app.debug:
        logging.basicConfig(level=logging.INFO)

    return app


def register_cli(app):
    """Register custom CLI commands with the Flask app."""

    @app.cli.command("seed-admin")
    @click.option("--email", default="admin@waas.local", help="Admin email")
    @click.option("--password", default="admin123", help="Admin password")
    def seed_admin(email, password):
        """Create admin user + demo prospect + workspace + site + invite token.

        Usage:
            flask seed-admin
            flask seed-admin --email admin@example.com --password s3cret
        """
        import secrets
        from datetime import datetime, timedelta, timezone

        from app.models.user import User
        from app.models.prospect import Prospect
        from app.models.workspace import Workspace, WorkspaceMember, WorkspaceSettings
        from app.models.site import Site
        from app.models.invite import WorkspaceInvite

        # --- 1. Admin user ---
        existing = User.query.filter_by(email=email).first()
        if existing:
            click.echo(f"Admin user already exists: {email}")
            admin = existing
        else:
            admin = User(
                email=email,
                password_hash=generate_password_hash(password),
                full_name="Admin",
                is_admin=True,
            )
            db.session.add(admin)
            db.session.flush()
            click.echo(f"Created admin user: {email}")

        # --- 2. Demo prospect ---
        prospect = Prospect(
            business_name="Demo Pizza Shop",
            contact_name="Joe Demo",
            contact_email="joe@demopizza.com",
            contact_phone="555-0100",
            source="google_maps",
            source_url="https://maps.google.com/example",
            notes="Demo prospect for testing. Great reviews, no website.",
            demo_url="https://demopizza.yourdomain.dev",
            status="converted",
        )
        db.session.add(prospect)
        db.session.flush()

        # --- 3. Workspace ---
        workspace = Workspace(
            name="Demo Pizza Shop",
            prospect_id=prospect.id,
        )
        db.session.add(workspace)
        db.session.flush()

        # Link prospect back to workspace
        prospect.workspace_id = workspace.id

        # --- 4. Workspace settings ---
        settings = WorkspaceSettings(workspace_id=workspace.id)
        db.session.add(settings)

        # --- 5. Admin as workspace member ---
        membership = WorkspaceMember(
            user_id=admin.id,
            workspace_id=workspace.id,
            role="owner",
        )
        db.session.add(membership)

        # --- 6. Site ---
        site = Site(
            workspace_id=workspace.id,
            site_slug="demo-pizza",
            display_name="Demo Pizza Shop",
            published_url="https://demopizza.yourdomain.dev",
            status="demo",
        )
        db.session.add(site)
        db.session.flush()

        # --- 7. Invite token ---
        token = secrets.token_urlsafe(48)  # 64-char base64 string
        invite = WorkspaceInvite(
            workspace_id=workspace.id,
            site_id=site.id,
            email="joe@demopizza.com",
            token=token,
            expires_at=datetime.now(timezone.utc) + timedelta(days=45),
        )
        db.session.add(invite)

        db.session.commit()

        base_url = app.config["APP_BASE_URL"]

        click.echo("")
        click.echo("=" * 60)
        click.echo("Seed data created successfully!")
        click.echo("=" * 60)
        click.echo(f"  Admin:     {email} / {password}")
        click.echo(f"  Prospect:  {prospect.business_name} (id: {prospect.id})")
        click.echo(f"  Workspace: {workspace.name} (id: {workspace.id})")
        click.echo(f"  Site:      {site.site_slug} (id: {site.id})")
        click.echo(f"  Invite:    {base_url}/auth/register?token={token}")
        click.echo(f"  Expires:   {invite.expires_at.isoformat()}")
        click.echo("=" * 60)

    @app.cli.command("create-setup-price")
    def create_setup_price():
        """Create the one-time $250 Website Setup Fee price in Stripe.

        Run once, then copy the printed price ID into the
        STRIPE_SETUP_PRICE_ID environment variable.

        Note: Not needed when PROMO_NO_SETUP_FEE=true — the setup fee
        is waived and this price ID is not used during checkout.
        """
        import stripe as _stripe

        _stripe.api_key = app.config["STRIPE_SECRET_KEY"]

        price = _stripe.Price.create(
            unit_amount=25000,  # $250.00
            currency="usd",
            product_data={
                "name": "Website Setup Fee",
                "statement_descriptor": "BD SETUP FEE",
            },
            metadata={
                "type": "setup_fee",
                "description": "One-time website build and setup fee. First month of hosting ($59) included free.",
            },
        )

        click.echo("")
        click.echo("=" * 60)
        click.echo("Stripe setup price created!")
        click.echo("=" * 60)
        click.echo(f"  Price ID:  {price.id}")
        click.echo(f"  Amount:    ${price.unit_amount / 100:.2f} {price.currency.upper()}")
        click.echo(f"  Type:      one_time")
        click.echo("")
        click.echo("Add this to your environment variables:")
        click.echo(f"  STRIPE_SETUP_PRICE_ID={price.id}")
        click.echo("=" * 60)

    @app.cli.command("verify-stripe-prices")
    def verify_stripe_prices():
        """Verify configured Stripe price IDs exist and are usable (same mode as key).

        Uses STRIPE_SECRET_KEY, STRIPE_SETUP_PRICE_ID, STRIPE_BASIC_PRICE_ID from env.
        Run with prod env vars to confirm Live prices; run with test vars for Test mode.
        """
        import stripe as _stripe

        api_key = app.config.get("STRIPE_SECRET_KEY")
        setup_id = app.config.get("STRIPE_SETUP_PRICE_ID")
        basic_id = app.config.get("STRIPE_BASIC_PRICE_ID")

        if not api_key:
            click.echo("ERROR: STRIPE_SECRET_KEY is not set.")
            return
        key_mode = "Live" if api_key.startswith("sk_live_") else "Test"
        click.echo(f"Stripe key mode: {key_mode}")
        click.echo("")

        _stripe.api_key = api_key

        def check_price(label: str, price_id: str) -> None:
            if not price_id:
                click.echo(f"  {label}: (not set)")
                return
            try:
                price = _stripe.Price.retrieve(price_id, expand=["product"])
                product = price.get("product")
                if isinstance(product, dict):
                    product_active = product.get("active", "?")
                else:
                    prod_id = getattr(price, "product", None) or price.get("product")
                    prod = _stripe.Product.retrieve(prod_id) if prod_id else None
                    product_active = getattr(prod, "active", "?") if prod else "?"
                livemode = getattr(price, "livemode", "?")
                click.echo(f"  {label}: {price_id}")
                click.echo(f"    exists=True, livemode={livemode}, product_active={product_active}")
                if livemode is True and key_mode != "Live":
                    click.echo("    WARNING: This price is Live but your key is Test.")
                elif livemode is False and key_mode == "Live":
                    click.echo("    WARNING: This price is Test but your key is Live.")
            except _stripe.error.InvalidRequestError as e:
                click.echo(f"  {label}: {price_id}")
                click.echo(f"    ERROR: {e}")
            click.echo("")

        click.echo("STRIPE_SETUP_PRICE_ID (setup fee):")
        check_price("setup", setup_id)
        click.echo("STRIPE_BASIC_PRICE_ID (monthly):")
        check_price("basic", basic_id)

    @app.cli.command("send-reminders")
    @click.option("--dry-run", is_flag=True, help="Show what would be sent without actually sending.")
    def send_reminders(dry_run):
        """Send D3/D10/D30 follow-up emails to pitched prospects.

        Finds prospects with status "pitched" who have an email, checks
        how many days since their first outreach email, and sends the
        appropriate reminder (D3, D10, or D30) if not already sent.

        Usage:
            flask send-reminders
            flask send-reminders --dry-run
        """
        from app.services.reminder_service import process_reminders
        process_reminders(dry_run=dry_run)
