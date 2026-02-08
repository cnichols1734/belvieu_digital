"""Tests for the webhooks blueprint and Stripe event handling.

Covers:
- Webhook signature verification (missing, invalid)
- Idempotent event processing (duplicate events skipped)
- checkout.session.completed handler
- customer.subscription.updated handler
- customer.subscription.deleted handler
- invoice.payment_failed handler
- invoice.payment_succeeded handler
- Unknown event types (accepted but not processed)
- Site status derivation from subscription status
"""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.extensions import db
from app.models.billing import BillingCustomer, BillingSubscription
from app.models.stripe_event import StripeEvent
from app.models.site import Site
from app.models.audit import AuditEvent


class TestWebhookSignature:
    """Tests for webhook signature validation."""

    def test_missing_signature_returns_400(self, client, seed_data):
        """POST /stripe/webhooks without signature -> 400."""
        resp = client.post(
            "/stripe/webhooks",
            data="{}",
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert b"Missing signature" in resp.data

    @patch("app.services.stripe_service.stripe.Webhook.construct_event")
    def test_invalid_signature_returns_400(self, mock_construct, client, seed_data):
        """POST /stripe/webhooks with bad signature -> 400."""
        mock_construct.side_effect = Exception("Invalid signature")

        resp = client.post(
            "/stripe/webhooks",
            data="{}",
            content_type="application/json",
            headers={"Stripe-Signature": "bad_sig"},
        )
        assert resp.status_code == 400
        assert b"Invalid signature" in resp.data


class TestWebhookIdempotency:
    """Tests for duplicate event handling."""

    @patch("app.services.stripe_service.stripe.Webhook.construct_event")
    def test_duplicate_event_returns_200(self, mock_construct, client, seed_data, app):
        """Duplicate event_id -> 200 with 'already_processed'."""
        # Pre-insert the event
        with app.app_context():
            existing = StripeEvent(
                stripe_event_id="evt_duplicate_123",
                event_type="checkout.session.completed",
            )
            db.session.add(existing)
            db.session.commit()

        mock_construct.return_value = {
            "id": "evt_duplicate_123",
            "type": "checkout.session.completed",
            "data": {"object": {}},
        }

        resp = client.post(
            "/stripe/webhooks",
            data="{}",
            content_type="application/json",
            headers={"Stripe-Signature": "valid_sig"},
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "already_processed"


class TestCheckoutCompleted:
    """Tests for checkout.session.completed webhook."""

    @patch("app.services.stripe_service.stripe.Subscription.retrieve")
    @patch("app.services.stripe_service.stripe.Webhook.construct_event")
    def test_creates_subscription(self, mock_construct, mock_sub_retrieve,
                                   client, seed_data, app):
        """checkout.session.completed -> creates BillingSubscription + BillingCustomer."""
        mock_construct.return_value = {
            "id": "evt_checkout_001",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "subscription": "sub_stripe_new",
                    "customer": "cus_stripe_new",
                    "metadata": {
                        "workspace_id": seed_data["workspace_id"],
                        "site_id": seed_data["site_id"],
                        "site_slug": "test-pizza",
                    },
                }
            },
        }

        mock_sub_retrieve.return_value = {
            "id": "sub_stripe_new",
            "status": "active",
            "current_period_end": 1798761600,  # some future timestamp
            "cancel_at_period_end": False,
            "items": {
                "data": [{"price": {"id": "price_basic_test"}}]
            },
        }

        resp = client.post(
            "/stripe/webhooks",
            data="{}",
            content_type="application/json",
            headers={"Stripe-Signature": "valid_sig"},
        )
        assert resp.status_code == 200

        with app.app_context():
            # Subscription created
            sub = BillingSubscription.query.filter_by(
                stripe_subscription_id="sub_stripe_new"
            ).first()
            assert sub is not None
            assert sub.status == "active"
            assert sub.plan == "basic"
            assert sub.workspace_id == seed_data["workspace_id"]

            # Billing customer created
            cust = BillingCustomer.query.filter_by(
                stripe_customer_id="cus_stripe_new"
            ).first()
            assert cust is not None

            # Site status derived
            site = Site.query.filter_by(site_slug="test-pizza").first()
            assert site.status == "active"

            # Stripe event recorded
            evt = StripeEvent.query.filter_by(
                stripe_event_id="evt_checkout_001"
            ).first()
            assert evt is not None
            assert evt.event_type == "checkout.session.completed"

            # Audit event logged
            audit = AuditEvent.query.filter_by(
                action="subscription.created"
            ).first()
            assert audit is not None


class TestSubscriptionUpdated:
    """Tests for customer.subscription.updated webhook."""

    def _setup_existing_sub(self, app, seed_data):
        """Create billing customer + subscription for update tests."""
        with app.app_context():
            customer = BillingCustomer(
                workspace_id=seed_data["workspace_id"],
                stripe_customer_id="cus_existing",
            )
            db.session.add(customer)

            sub = BillingSubscription(
                workspace_id=seed_data["workspace_id"],
                stripe_subscription_id="sub_existing",
                stripe_price_id="price_basic_test",
                plan="basic",
                status="active",
                current_period_end=datetime(2026, 12, 31, tzinfo=timezone.utc),
            )
            db.session.add(sub)
            db.session.commit()

    @patch("app.services.stripe_service.stripe.Webhook.construct_event")
    def test_updates_subscription_status(self, mock_construct, client, seed_data, app):
        """subscription.updated -> updates status and period end."""
        self._setup_existing_sub(app, seed_data)

        mock_construct.return_value = {
            "id": "evt_update_001",
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_existing",
                    "customer": "cus_existing",
                    "status": "past_due",
                    "current_period_end": 1798761600,
                    "cancel_at_period_end": False,
                    "items": {
                        "data": [{"price": {"id": "price_basic_test"}}]
                    },
                }
            },
        }

        resp = client.post(
            "/stripe/webhooks",
            data="{}",
            content_type="application/json",
            headers={"Stripe-Signature": "valid_sig"},
        )
        assert resp.status_code == 200

        with app.app_context():
            sub = BillingSubscription.query.filter_by(
                stripe_subscription_id="sub_existing"
            ).first()
            assert sub.status == "past_due"

    @patch("app.services.stripe_service.stripe.Webhook.construct_event")
    def test_updates_cancel_at_period_end(self, mock_construct, client, seed_data, app):
        """subscription.updated with cancel_at_period_end -> updates flag."""
        self._setup_existing_sub(app, seed_data)

        mock_construct.return_value = {
            "id": "evt_update_002",
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_existing",
                    "customer": "cus_existing",
                    "status": "active",
                    "current_period_end": 1798761600,
                    "cancel_at_period_end": True,
                    "items": {
                        "data": [{"price": {"id": "price_basic_test"}}]
                    },
                }
            },
        }

        resp = client.post(
            "/stripe/webhooks",
            data="{}",
            content_type="application/json",
            headers={"Stripe-Signature": "valid_sig"},
        )
        assert resp.status_code == 200

        with app.app_context():
            sub = BillingSubscription.query.filter_by(
                stripe_subscription_id="sub_existing"
            ).first()
            assert sub.cancel_at_period_end is True


class TestSubscriptionDeleted:
    """Tests for customer.subscription.deleted webhook."""

    def _setup_existing_sub(self, app, seed_data):
        """Create billing customer + subscription for delete tests."""
        with app.app_context():
            customer = BillingCustomer(
                workspace_id=seed_data["workspace_id"],
                stripe_customer_id="cus_del",
            )
            db.session.add(customer)

            sub = BillingSubscription(
                workspace_id=seed_data["workspace_id"],
                stripe_subscription_id="sub_del",
                stripe_price_id="price_basic_test",
                plan="basic",
                status="active",
            )
            db.session.add(sub)
            db.session.commit()

    @patch("app.services.stripe_service.stripe.Webhook.construct_event")
    def test_marks_subscription_canceled(self, mock_construct, client, seed_data, app):
        """subscription.deleted -> marks status=canceled, site=paused."""
        self._setup_existing_sub(app, seed_data)

        mock_construct.return_value = {
            "id": "evt_delete_001",
            "type": "customer.subscription.deleted",
            "data": {
                "object": {
                    "id": "sub_del",
                    "customer": "cus_del",
                }
            },
        }

        resp = client.post(
            "/stripe/webhooks",
            data="{}",
            content_type="application/json",
            headers={"Stripe-Signature": "valid_sig"},
        )
        assert resp.status_code == 200

        with app.app_context():
            sub = BillingSubscription.query.filter_by(
                stripe_subscription_id="sub_del"
            ).first()
            assert sub.status == "canceled"

            site = Site.query.filter_by(site_slug="test-pizza").first()
            assert site.status == "paused"


class TestPaymentFailed:
    """Tests for invoice.payment_failed webhook."""

    def _setup_existing_sub(self, app, seed_data):
        """Create billing customer + subscription."""
        with app.app_context():
            customer = BillingCustomer(
                workspace_id=seed_data["workspace_id"],
                stripe_customer_id="cus_fail",
            )
            db.session.add(customer)

            sub = BillingSubscription(
                workspace_id=seed_data["workspace_id"],
                stripe_subscription_id="sub_fail",
                stripe_price_id="price_basic_test",
                plan="basic",
                status="active",
            )
            db.session.add(sub)
            db.session.commit()

    @patch("app.services.stripe_service.stripe.Webhook.construct_event")
    def test_sets_past_due(self, mock_construct, client, seed_data, app):
        """payment_failed -> sets subscription to past_due."""
        self._setup_existing_sub(app, seed_data)

        mock_construct.return_value = {
            "id": "evt_fail_001",
            "type": "invoice.payment_failed",
            "data": {
                "object": {
                    "customer": "cus_fail",
                    "subscription": "sub_fail",
                    "amount_due": 5900,
                }
            },
        }

        resp = client.post(
            "/stripe/webhooks",
            data="{}",
            content_type="application/json",
            headers={"Stripe-Signature": "valid_sig"},
        )
        assert resp.status_code == 200

        with app.app_context():
            sub = BillingSubscription.query.filter_by(
                stripe_subscription_id="sub_fail"
            ).first()
            assert sub.status == "past_due"


class TestPaymentSucceeded:
    """Tests for invoice.payment_succeeded webhook."""

    def _setup_past_due_sub(self, app, seed_data):
        """Create billing customer + past_due subscription."""
        with app.app_context():
            customer = BillingCustomer(
                workspace_id=seed_data["workspace_id"],
                stripe_customer_id="cus_succeed",
            )
            db.session.add(customer)

            sub = BillingSubscription(
                workspace_id=seed_data["workspace_id"],
                stripe_subscription_id="sub_succeed",
                stripe_price_id="price_basic_test",
                plan="basic",
                status="past_due",
            )
            db.session.add(sub)
            db.session.commit()

    @patch("app.services.stripe_service.stripe.Webhook.construct_event")
    def test_reactivates_subscription(self, mock_construct, client, seed_data, app):
        """payment_succeeded on past_due sub -> sets active, site active."""
        self._setup_past_due_sub(app, seed_data)

        mock_construct.return_value = {
            "id": "evt_succeed_001",
            "type": "invoice.payment_succeeded",
            "data": {
                "object": {
                    "customer": "cus_succeed",
                    "subscription": "sub_succeed",
                    "amount_paid": 5900,
                }
            },
        }

        resp = client.post(
            "/stripe/webhooks",
            data="{}",
            content_type="application/json",
            headers={"Stripe-Signature": "valid_sig"},
        )
        assert resp.status_code == 200

        with app.app_context():
            sub = BillingSubscription.query.filter_by(
                stripe_subscription_id="sub_succeed"
            ).first()
            assert sub.status == "active"

            site = Site.query.filter_by(site_slug="test-pizza").first()
            assert site.status == "active"


class TestUnknownEvent:
    """Tests for unhandled event types."""

    @patch("app.services.stripe_service.stripe.Webhook.construct_event")
    def test_unknown_event_accepted(self, mock_construct, client, seed_data, app):
        """Unknown event type -> 200, recorded but no handler called."""
        mock_construct.return_value = {
            "id": "evt_unknown_001",
            "type": "some.unknown.event",
            "data": {"object": {}},
        }

        resp = client.post(
            "/stripe/webhooks",
            data="{}",
            content_type="application/json",
            headers={"Stripe-Signature": "valid_sig"},
        )
        assert resp.status_code == 200

        with app.app_context():
            evt = StripeEvent.query.filter_by(
                stripe_event_id="evt_unknown_001"
            ).first()
            assert evt is not None
            assert evt.event_type == "some.unknown.event"
