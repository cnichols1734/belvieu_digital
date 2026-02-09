"""Tests for the portal blueprint and tenant middleware.

Covers:
- Tenant resolution (valid slug, invalid slug)
- Dashboard rendering by access level
- Subscribe page for no-subscription state
- Suspended page for canceled subscription
- Past-due warning banner
- Unauthenticated redirect to login
- Non-member access denied
"""

from datetime import datetime, timezone

from app.extensions import db
from app.models.user import User
from app.models.workspace import WorkspaceMember
from app.models.billing import BillingSubscription
from werkzeug.security import generate_password_hash


class TestTenantResolution:
    """Tests for the tenant middleware slug resolution."""

    def test_valid_slug_resolves(self, client, seed_data):
        """GET /<valid_slug>/dashboard should not 404 (redirects to login)."""
        resp = client.get("/test-pizza/dashboard", follow_redirects=False)
        # Should redirect to login (not authenticated)
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]

    def test_invalid_slug_returns_404(self, client, seed_data):
        """GET /<invalid_slug>/dashboard should return 404."""
        resp = client.get("/nonexistent-slug/dashboard")
        assert resp.status_code == 404

    def test_root_slug_redirects(self, client, seed_data):
        """GET /<slug>/ should redirect to dashboard or login."""
        resp = client.get("/test-pizza/", follow_redirects=False)
        assert resp.status_code == 302


class TestDashboard:
    """Tests for the portal dashboard by access level."""

    def _login(self, client, email, password):
        """Helper to log in."""
        return client.post(
            "/auth/login",
            data={"email": email, "password": password},
            follow_redirects=False,
        )

    def _create_client_user(self, app, seed_data):
        """Create a regular client user with workspace membership."""
        with app.app_context():
            user = User(
                email="client@test.com",
                password_hash=generate_password_hash("clientpass123"),
                full_name="Client User",
            )
            db.session.add(user)
            db.session.flush()

            membership = WorkspaceMember(
                user_id=user.id,
                workspace_id=seed_data["workspace_id"],
                role="owner",
            )
            db.session.add(membership)
            db.session.commit()
            return user.id

    def test_dashboard_no_subscription_shows_subscribe(self, client, seed_data, app):
        """Dashboard with no subscription -> subscribe page."""
        self._create_client_user(app, seed_data)
        self._login(client, "client@test.com", "clientpass123")

        resp = client.get("/test-pizza/dashboard")
        assert resp.status_code == 200
        assert b"Welcome to Belvieu Digital" in resp.data

    def test_dashboard_active_subscription(self, client, seed_data, app):
        """Dashboard with active subscription -> full dashboard."""
        user_id = self._create_client_user(app, seed_data)
        self._login(client, "client@test.com", "clientpass123")

        with app.app_context():
            sub = BillingSubscription(
                workspace_id=seed_data["workspace_id"],
                stripe_subscription_id="sub_test_active",
                stripe_price_id="price_basic_test",
                plan="basic",
                status="active",
                current_period_end=datetime(2026, 12, 31, tzinfo=timezone.utc),
            )
            db.session.add(sub)
            db.session.commit()

        resp = client.get("/test-pizza/dashboard")
        assert resp.status_code == 200
        assert b"Welcome back" in resp.data
        assert b"Basic" in resp.data
        assert b"Active" in resp.data

    def test_dashboard_past_due_shows_warning(self, client, seed_data, app):
        """Dashboard with past_due subscription -> warning banner."""
        self._create_client_user(app, seed_data)
        self._login(client, "client@test.com", "clientpass123")

        with app.app_context():
            sub = BillingSubscription(
                workspace_id=seed_data["workspace_id"],
                stripe_subscription_id="sub_test_pastdue",
                stripe_price_id="price_basic_test",
                plan="basic",
                status="past_due",
                current_period_end=datetime(2026, 12, 31, tzinfo=timezone.utc),
            )
            db.session.add(sub)
            db.session.commit()

        resp = client.get("/test-pizza/dashboard")
        assert resp.status_code == 200
        assert b"Payment failed" in resp.data

    def test_dashboard_canceled_shows_suspended(self, client, seed_data, app):
        """Dashboard with canceled subscription -> suspended page."""
        self._create_client_user(app, seed_data)
        self._login(client, "client@test.com", "clientpass123")

        with app.app_context():
            sub = BillingSubscription(
                workspace_id=seed_data["workspace_id"],
                stripe_subscription_id="sub_test_canceled",
                stripe_price_id="price_basic_test",
                plan="basic",
                status="canceled",
            )
            db.session.add(sub)
            db.session.commit()

        resp = client.get("/test-pizza/dashboard")
        assert resp.status_code == 200
        assert b"subscription has ended" in resp.data.lower()

    def test_dashboard_unauthenticated_redirects(self, client, seed_data):
        """Unauthenticated access to dashboard -> redirect to login."""
        resp = client.get("/test-pizza/dashboard", follow_redirects=False)
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]

    def test_dashboard_non_member_gets_403(self, client, seed_data, app):
        """User who is not a workspace member -> 403."""
        with app.app_context():
            outsider = User(
                email="outsider@test.com",
                password_hash=generate_password_hash("outsider123"),
                full_name="Outsider",
            )
            db.session.add(outsider)
            db.session.commit()

        self._login(client, "outsider@test.com", "outsider123")
        resp = client.get("/test-pizza/dashboard")
        assert resp.status_code == 403
