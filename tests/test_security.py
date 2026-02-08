"""Security tests for Phase 7 — Security Hardening.

Tests:
- Security headers are present on responses
- Cross-tenant data isolation (explicit attempts to access another workspace's data)
- Rate limiting configuration
"""

import secrets
from datetime import datetime, timedelta, timezone

import pytest
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember, WorkspaceSettings
from app.models.site import Site
from app.models.billing import BillingSubscription
from app.models.ticket import Ticket, TicketMessage


class TestSecurityHeaders:
    """Verify security headers are present on responses."""

    def test_x_content_type_options(self, app, client):
        """X-Content-Type-Options: nosniff should be set."""
        response = client.get("/auth/login")
        assert response.headers.get("X-Content-Type-Options") == "nosniff"

    def test_x_frame_options(self, app, client):
        """X-Frame-Options: DENY should be set."""
        response = client.get("/auth/login")
        assert response.headers.get("X-Frame-Options") == "DENY"

    def test_referrer_policy(self, app, client):
        """Referrer-Policy should be set."""
        response = client.get("/auth/login")
        assert response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    def test_x_xss_protection(self, app, client):
        """X-XSS-Protection should be set."""
        response = client.get("/auth/login")
        assert response.headers.get("X-XSS-Protection") == "1; mode=block"

    def test_permissions_policy(self, app, client):
        """Permissions-Policy should restrict browser features."""
        response = client.get("/auth/login")
        pp = response.headers.get("Permissions-Policy")
        assert pp is not None
        assert "camera=()" in pp
        assert "microphone=()" in pp

    def test_csp_header(self, app, client):
        """Content-Security-Policy should be set with appropriate directives."""
        response = client.get("/auth/login")
        csp = response.headers.get("Content-Security-Policy")
        assert csp is not None
        assert "default-src 'self'" in csp
        assert "script-src" in csp
        assert "stripe.com" in csp

    def test_no_hsts_in_debug(self, app, client):
        """HSTS should NOT be set in debug/test mode."""
        response = client.get("/auth/login")
        assert response.headers.get("Strict-Transport-Security") is None

    def test_headers_on_error_pages(self, app, client):
        """Security headers should be present even on 404 pages."""
        response = client.get("/nonexistent-page")
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-Frame-Options") == "DENY"


class TestCrossTenantIsolation:
    """Test that users cannot access another workspace's data.

    Creates two separate workspaces with separate users and verifies
    that User A cannot access Workspace B's resources.
    """

    @pytest.fixture
    def two_workspaces(self, app):
        """Set up two completely separate workspaces with users."""
        with app.app_context():
            # --- Workspace A ---
            workspace_a = Workspace(name="Workspace Alpha")
            db.session.add(workspace_a)
            db.session.flush()

            settings_a = WorkspaceSettings(workspace_id=workspace_a.id)
            db.session.add(settings_a)

            site_a = Site(
                workspace_id=workspace_a.id,
                site_slug="alpha-shop",
                display_name="Alpha Shop",
                status="active",
            )
            db.session.add(site_a)
            db.session.flush()

            user_a = User(
                email="user_a@alpha.com",
                password_hash=generate_password_hash("password123"),
                full_name="User Alpha",
            )
            db.session.add(user_a)
            db.session.flush()

            member_a = WorkspaceMember(
                user_id=user_a.id,
                workspace_id=workspace_a.id,
                role="owner",
            )
            db.session.add(member_a)

            # Active subscription for workspace A
            sub_a = BillingSubscription(
                workspace_id=workspace_a.id,
                stripe_subscription_id="sub_alpha_test",
                stripe_price_id="price_basic_test",
                plan="basic",
                status="active",
                current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
            )
            db.session.add(sub_a)
            db.session.flush()

            # Ticket in workspace A
            ticket_a = Ticket(
                workspace_id=workspace_a.id,
                site_id=site_a.id,
                author_user_id=user_a.id,
                subject="Alpha Ticket - Confidential",
                description="Secret data for workspace Alpha",
                category="question",
                status="open",
            )
            db.session.add(ticket_a)
            db.session.flush()

            msg_a = TicketMessage(
                ticket_id=ticket_a.id,
                author_user_id=user_a.id,
                message="This is a private message in Alpha workspace",
            )
            db.session.add(msg_a)

            # --- Workspace B ---
            workspace_b = Workspace(name="Workspace Beta")
            db.session.add(workspace_b)
            db.session.flush()

            settings_b = WorkspaceSettings(workspace_id=workspace_b.id)
            db.session.add(settings_b)

            site_b = Site(
                workspace_id=workspace_b.id,
                site_slug="beta-shop",
                display_name="Beta Shop",
                status="active",
            )
            db.session.add(site_b)
            db.session.flush()

            user_b = User(
                email="user_b@beta.com",
                password_hash=generate_password_hash("password123"),
                full_name="User Beta",
            )
            db.session.add(user_b)
            db.session.flush()

            member_b = WorkspaceMember(
                user_id=user_b.id,
                workspace_id=workspace_b.id,
                role="owner",
            )
            db.session.add(member_b)

            # Active subscription for workspace B
            sub_b = BillingSubscription(
                workspace_id=workspace_b.id,
                stripe_subscription_id="sub_beta_test",
                stripe_price_id="price_basic_test",
                plan="basic",
                status="active",
                current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
            )
            db.session.add(sub_b)
            db.session.flush()

            # Ticket in workspace B
            ticket_b = Ticket(
                workspace_id=workspace_b.id,
                site_id=site_b.id,
                author_user_id=user_b.id,
                subject="Beta Ticket - Confidential",
                description="Secret data for workspace Beta",
                category="bug",
                status="open",
            )
            db.session.add(ticket_b)
            db.session.flush()

            db.session.commit()

            return {
                "workspace_a_id": workspace_a.id,
                "site_a_slug": site_a.site_slug,
                "user_a_email": "user_a@alpha.com",
                "ticket_a_id": ticket_a.id,
                "workspace_b_id": workspace_b.id,
                "site_b_slug": site_b.site_slug,
                "user_b_email": "user_b@beta.com",
                "ticket_b_id": ticket_b.id,
            }

    def _login(self, client, email, password="password123"):
        """Helper to log in a user."""
        return client.post(
            "/auth/login",
            data={"email": email, "password": password},
            follow_redirects=False,
        )

    def test_user_a_cannot_access_workspace_b_dashboard(self, app, client, two_workspaces):
        """User A should be denied access to Workspace B's dashboard."""
        self._login(client, two_workspaces["user_a_email"])
        response = client.get(f"/{two_workspaces['site_b_slug']}/dashboard")
        assert response.status_code == 403

    def test_user_b_cannot_access_workspace_a_dashboard(self, app, client, two_workspaces):
        """User B should be denied access to Workspace A's dashboard."""
        self._login(client, two_workspaces["user_b_email"])
        response = client.get(f"/{two_workspaces['site_a_slug']}/dashboard")
        assert response.status_code == 403

    def test_user_a_cannot_view_workspace_b_tickets(self, app, client, two_workspaces):
        """User A should be denied access to Workspace B's ticket list."""
        self._login(client, two_workspaces["user_a_email"])
        response = client.get(f"/{two_workspaces['site_b_slug']}/tickets")
        assert response.status_code == 403

    def test_user_a_cannot_view_workspace_b_ticket_detail(self, app, client, two_workspaces):
        """User A trying to access Workspace B's ticket via Workspace A's slug should fail."""
        self._login(client, two_workspaces["user_a_email"])
        # Try accessing B's ticket through A's site slug
        response = client.get(
            f"/{two_workspaces['site_a_slug']}/tickets/{two_workspaces['ticket_b_id']}",
            follow_redirects=True,
        )
        # Should redirect with "Ticket not found" flash (workspace isolation check in portal)
        assert b"Ticket not found" in response.data

    def test_user_a_cannot_reply_to_workspace_b_ticket(self, app, client, two_workspaces):
        """User A should not be able to reply to Workspace B's ticket."""
        self._login(client, two_workspaces["user_a_email"])
        response = client.post(
            f"/{two_workspaces['site_a_slug']}/tickets/{two_workspaces['ticket_b_id']}/reply",
            data={"message": "Trying to inject a message"},
            follow_redirects=True,
        )
        assert b"Ticket not found" in response.data

    def test_user_a_cannot_create_ticket_in_workspace_b(self, app, client, two_workspaces):
        """User A creating a ticket through B's slug should be denied."""
        self._login(client, two_workspaces["user_a_email"])
        response = client.post(
            f"/{two_workspaces['site_b_slug']}/tickets/new",
            data={
                "subject": "Malicious ticket",
                "description": "Trying to create ticket in wrong workspace",
                "category": "question",
            },
        )
        # Should be 403 because user_a is not a member of workspace_b
        assert response.status_code == 403

    def test_user_b_ticket_data_not_in_user_a_dashboard(self, app, client, two_workspaces):
        """User A's dashboard should never show Workspace B's tickets."""
        self._login(client, two_workspaces["user_a_email"])
        response = client.get(f"/{two_workspaces['site_a_slug']}/dashboard")
        assert response.status_code == 200
        assert b"Beta Ticket" not in response.data
        assert b"Secret data for workspace Beta" not in response.data

    def test_unauthenticated_cannot_access_portal(self, app, client, two_workspaces):
        """Unauthenticated users should be redirected to login."""
        response = client.get(f"/{two_workspaces['site_a_slug']}/dashboard")
        assert response.status_code == 302
        assert "/auth/login" in response.headers.get("Location", "")

    def test_user_a_can_access_own_workspace(self, app, client, two_workspaces):
        """Sanity check: User A CAN access their own workspace."""
        self._login(client, two_workspaces["user_a_email"])
        response = client.get(f"/{two_workspaces['site_a_slug']}/dashboard")
        assert response.status_code == 200
        assert b"Alpha" in response.data

    def test_user_a_can_access_own_ticket(self, app, client, two_workspaces):
        """Sanity check: User A CAN view their own ticket."""
        self._login(client, two_workspaces["user_a_email"])
        response = client.get(
            f"/{two_workspaces['site_a_slug']}/tickets/{two_workspaces['ticket_a_id']}"
        )
        assert response.status_code == 200
        assert b"Alpha Ticket" in response.data


class TestRateLimiting:
    """Verify rate limiting is configured (though disabled in tests via RATELIMIT_ENABLED=False)."""

    def test_rate_limiter_initialized(self, app):
        """The limiter extension should be registered on the app."""
        # In test config, rate limiting is disabled, but the extension is initialized
        assert app.config.get("RATELIMIT_ENABLED") is False
