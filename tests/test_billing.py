"""Tests for the billing blueprint.

Covers:
- Checkout route (creates Stripe session, redirects)
- Checkout with invalid price_id
- Checkout success page
- Checkout cancel redirect
- Customer portal route (creates portal session, redirects)
- Customer portal without billing customer
- Billing overview page (active subscriber vs no subscription)
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.extensions import db
from app.models.user import User
from app.models.workspace import WorkspaceMember
from app.models.billing import BillingCustomer, BillingSubscription
from werkzeug.security import generate_password_hash


class TestBilling:
    """Tests for the billing blueprint routes."""

    def _create_client_and_login(self, app, client, seed_data):
        """Create a client user with workspace membership and log in."""
        with app.app_context():
            user = User(
                email="billing-client@test.com",
                password_hash=generate_password_hash("clientpass123"),
                full_name="Billing Client",
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
            user_id = user.id

        client.post(
            "/auth/login",
            data={"email": "billing-client@test.com", "password": "clientpass123"},
            follow_redirects=True,
        )
        return user_id

    def _add_subscription(self, app, seed_data, status="active", plan="basic"):
        """Add a billing subscription for the workspace."""
        with app.app_context():
            customer = BillingCustomer(
                workspace_id=seed_data["workspace_id"],
                stripe_customer_id="cus_test_billing",
            )
            db.session.add(customer)

            sub = BillingSubscription(
                workspace_id=seed_data["workspace_id"],
                stripe_subscription_id="sub_test_billing",
                stripe_price_id="price_basic_test",
                plan=plan,
                status=status,
                current_period_end=datetime(2026, 12, 31, tzinfo=timezone.utc),
            )
            db.session.add(sub)
            db.session.commit()

    # ── Checkout ──

    @patch("app.services.stripe_service.stripe")
    def test_checkout_redirects_to_stripe(self, mock_stripe, client, seed_data, app):
        """POST /checkout with valid price_id -> redirect to Stripe."""
        self._create_client_and_login(app, client, seed_data)

        # Mock Stripe Customer.create and checkout.Session.create
        mock_stripe.Customer.create.return_value = MagicMock(id="cus_new_123")
        mock_stripe.checkout.Session.create.return_value = MagicMock(
            url="https://checkout.stripe.com/test-session"
        )

        resp = client.post(
            "/test-pizza/billing/checkout",
            data={"price_id": "price_basic_test"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "checkout.stripe.com" in resp.headers["Location"]

    def test_checkout_invalid_price_id(self, client, seed_data, app):
        """POST /checkout with invalid price_id -> redirect to dashboard with error."""
        self._create_client_and_login(app, client, seed_data)

        resp = client.post(
            "/test-pizza/billing/checkout",
            data={"price_id": "price_invalid_xxx"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/test-pizza/dashboard" in resp.headers["Location"]

    def test_checkout_missing_price_id(self, client, seed_data, app):
        """POST /checkout with no price_id -> redirect to dashboard with error."""
        self._create_client_and_login(app, client, seed_data)

        resp = client.post(
            "/test-pizza/billing/checkout",
            data={},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/test-pizza/dashboard" in resp.headers["Location"]

    @patch("app.services.stripe_service.stripe")
    def test_checkout_uses_existing_customer(self, mock_stripe, client, seed_data, app):
        """POST /checkout when BillingCustomer already exists -> uses existing."""
        self._create_client_and_login(app, client, seed_data)
        self._add_subscription(app, seed_data)

        mock_stripe.checkout.Session.create.return_value = MagicMock(
            url="https://checkout.stripe.com/test-session"
        )

        resp = client.post(
            "/test-pizza/billing/checkout",
            data={"price_id": "price_basic_test"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        # Should NOT have called Customer.create since one exists
        mock_stripe.Customer.create.assert_not_called()

    # ── Checkout Success & Cancel ──

    def test_checkout_success_page(self, client, seed_data, app):
        """GET /billing/success -> success page with redirect."""
        self._create_client_and_login(app, client, seed_data)

        resp = client.get("/test-pizza/billing/success")
        assert resp.status_code == 200
        assert b"Payment successful" in resp.data

    def test_checkout_cancel_redirects(self, client, seed_data, app):
        """GET /billing/cancel -> redirect to dashboard with flash."""
        self._create_client_and_login(app, client, seed_data)

        resp = client.get("/test-pizza/billing/cancel", follow_redirects=False)
        assert resp.status_code == 302
        assert "/test-pizza/dashboard" in resp.headers["Location"]

    # ── Customer Portal ──

    @patch("app.services.stripe_service.stripe")
    def test_portal_redirects_to_stripe(self, mock_stripe, client, seed_data, app):
        """POST /billing/portal with existing customer -> redirect to Stripe portal."""
        self._create_client_and_login(app, client, seed_data)
        self._add_subscription(app, seed_data)

        mock_stripe.billing_portal.Session.create.return_value = MagicMock(
            url="https://billing.stripe.com/test-portal"
        )

        resp = client.post(
            "/test-pizza/billing/portal",
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "billing.stripe.com" in resp.headers["Location"]

    def test_portal_no_billing_customer(self, client, seed_data, app):
        """POST /billing/portal without billing customer -> redirect with error."""
        self._create_client_and_login(app, client, seed_data)

        resp = client.post(
            "/test-pizza/billing/portal",
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/test-pizza/dashboard" in resp.headers["Location"]

    # ── Billing Overview ──

    def test_billing_overview_with_subscription(self, client, seed_data, app):
        """GET /billing with active subscription -> billing page."""
        self._create_client_and_login(app, client, seed_data)
        self._add_subscription(app, seed_data)

        resp = client.get("/test-pizza/billing")
        assert resp.status_code == 200
        assert b"Billing" in resp.data
        assert b"Manage billing" in resp.data

    def test_billing_overview_no_subscription(self, client, seed_data, app):
        """GET /billing with no subscription -> subscribe page."""
        self._create_client_and_login(app, client, seed_data)

        resp = client.get("/test-pizza/billing")
        assert resp.status_code == 200
        assert b"Welcome to Belvieu Digital" in resp.data

    # ── Auth Guards ──

    def test_checkout_requires_login(self, client, seed_data):
        """POST /checkout without login -> redirect to login."""
        resp = client.post(
            "/test-pizza/billing/checkout",
            data={"price_id": "price_basic_test"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]

    def test_portal_requires_login(self, client, seed_data):
        """POST /billing/portal without login -> redirect to login."""
        resp = client.post(
            "/test-pizza/billing/portal",
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]
