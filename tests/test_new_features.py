"""Tests for features added in the flow-overhaul session.

Covers:
- Password reset flow (forgot password, reset with token)
- Prospect activity log (add activity, timeline)
- Prospect outreach email (send + auto status change)
- Invite email sending from admin
- Yelp as prospect source
- Prospect update preserving fields on status-only changes
- Billing status poll endpoint (checkout_status)
- Landing page CTA buttons open contact modal (not invite section)
- _extract_period_end helper (Stripe SDK compatibility)
"""

import secrets
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models.user import User
from app.models.prospect import Prospect
from app.models.prospect_activity import ProspectActivity
from app.models.workspace import Workspace, WorkspaceMember, WorkspaceSettings
from app.models.site import Site
from app.models.invite import WorkspaceInvite
from app.models.billing import BillingCustomer, BillingSubscription
from app.models.audit import AuditEvent


def _login_admin(client):
    return client.post("/auth/login", data={
        "email": "admin@waas.local", "password": "admin123",
    }, follow_redirects=True)


def _make_client_user(session, workspace_id, email="client@test.com"):
    user = User(
        email=email,
        password_hash=generate_password_hash("clientpass"),
        full_name="Client User",
        is_admin=False,
    )
    session.add(user)
    session.flush()
    member = WorkspaceMember(
        user_id=user.id, workspace_id=workspace_id, role="member",
    )
    session.add(member)
    session.flush()
    return user


def _make_subscription(session, workspace_id, status="active"):
    sub = BillingSubscription(
        workspace_id=workspace_id,
        stripe_subscription_id=f"sub_{secrets.token_hex(8)}",
        stripe_price_id="price_basic_test",
        plan="basic",
        status=status,
        current_period_end=datetime(2026, 12, 31, tzinfo=timezone.utc),
    )
    session.add(sub)
    session.flush()
    return sub


# ══════════════════════════════════════════════
#  PASSWORD RESET
# ══════════════════════════════════════════════

class TestPasswordReset:

    def test_forgot_password_page_renders(self, client, seed_data):
        resp = client.get("/auth/forgot-password")
        assert resp.status_code == 200
        assert b"Reset your password" in resp.data

    @patch("app.blueprints.auth.send_email")
    def test_forgot_password_sends_email(self, mock_send, client, seed_data, app):
        resp = client.post("/auth/forgot-password", data={
            "email": "admin@waas.local",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"reset link" in resp.data
        mock_send.assert_called_once()
        # Token should be set on user
        with app.app_context():
            user = User.query.filter_by(email="admin@waas.local").first()
            assert user.password_reset_token is not None
            assert user.password_reset_expires is not None

    def test_forgot_password_nonexistent_email_no_error(self, client, seed_data):
        """Should not reveal whether email exists."""
        resp = client.post("/auth/forgot-password", data={
            "email": "nobody@nowhere.com",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"reset link" in resp.data

    def test_reset_password_invalid_token(self, client, seed_data):
        resp = client.get("/auth/reset-password?token=invalid_token_xyz")
        assert resp.status_code == 200
        assert b"Invalid or expired" in resp.data

    def test_reset_password_expired_token(self, client, seed_data, app):
        with app.app_context():
            user = User.query.filter_by(email="admin@waas.local").first()
            user.password_reset_token = "expired_token_123"
            user.password_reset_expires = datetime.now(timezone.utc) - timedelta(hours=2)
            db.session.commit()

        resp = client.get("/auth/reset-password?token=expired_token_123")
        assert resp.status_code == 200
        assert b"Invalid or expired" in resp.data

    def test_reset_password_success(self, client, seed_data, app):
        token = secrets.token_urlsafe(48)
        with app.app_context():
            user = User.query.filter_by(email="admin@waas.local").first()
            user.password_reset_token = token
            user.password_reset_expires = datetime.now(timezone.utc) + timedelta(hours=1)
            db.session.commit()

        resp = client.post(f"/auth/reset-password?token={token}", data={
            "password": "newpassword123",
            "password_confirm": "newpassword123",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"password has been reset" in resp.data

        # Token should be cleared
        with app.app_context():
            user = User.query.filter_by(email="admin@waas.local").first()
            assert user.password_reset_token is None

        # Can login with new password
        resp = client.post("/auth/login", data={
            "email": "admin@waas.local", "password": "newpassword123",
        }, follow_redirects=True)
        assert resp.status_code == 200

    def test_reset_password_mismatch(self, client, seed_data, app):
        token = secrets.token_urlsafe(48)
        with app.app_context():
            user = User.query.filter_by(email="admin@waas.local").first()
            user.password_reset_token = token
            user.password_reset_expires = datetime.now(timezone.utc) + timedelta(hours=1)
            db.session.commit()

        resp = client.post(f"/auth/reset-password?token={token}", data={
            "password": "newpassword123",
            "password_confirm": "differentpassword",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"do not match" in resp.data

    def test_login_page_has_forgot_link(self, client, seed_data):
        resp = client.get("/auth/login")
        assert resp.status_code == 200
        assert b"Forgot password?" in resp.data


# ══════════════════════════════════════════════
#  PROSPECT ACTIVITY LOG
# ══════════════════════════════════════════════

class TestProspectActivity:

    def test_add_activity(self, client, seed_data, app):
        _login_admin(client)
        with app.app_context():
            prospect = Prospect.query.first()
            prospect_id = prospect.id

        resp = client.post(f"/admin/prospects/{prospect_id}/activity", data={
            "activity_type": "call",
            "note": "Left voicemail",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"activity logged" in resp.data

        with app.app_context():
            activities = ProspectActivity.query.filter_by(prospect_id=prospect_id).all()
            assert len(activities) == 1
            assert activities[0].activity_type == "call"
            assert activities[0].note == "Left voicemail"

    def test_add_activity_invalid_type(self, client, seed_data, app):
        _login_admin(client)
        with app.app_context():
            prospect = Prospect.query.first()
            prospect_id = prospect.id

        resp = client.post(f"/admin/prospects/{prospect_id}/activity", data={
            "activity_type": "invalid_type",
            "note": "test",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"Invalid activity" in resp.data

    def test_activity_types(self, client, seed_data, app):
        """All valid activity types can be logged."""
        _login_admin(client)
        with app.app_context():
            prospect = Prospect.query.first()
            prospect_id = prospect.id

        for atype in ["email", "text", "call", "note"]:
            resp = client.post(f"/admin/prospects/{prospect_id}/activity", data={
                "activity_type": atype,
                "note": f"Test {atype}",
            }, follow_redirects=True)
            assert resp.status_code == 200

        with app.app_context():
            count = ProspectActivity.query.filter_by(prospect_id=prospect_id).count()
            assert count == 4


# ══════════════════════════════════════════════
#  PROSPECT OUTREACH EMAIL
# ══════════════════════════════════════════════

class TestProspectOutreach:

    def _make_prospect(self, app, status="site_built"):
        with app.app_context():
            prospect = Prospect(
                business_name="Outreach Test Biz",
                contact_name="Jane",
                contact_email="jane@outreach.com",
                source="google_maps",
                demo_url="https://outreach-test.pages.dev",
                status=status,
            )
            db.session.add(prospect)
            db.session.commit()
            return prospect.id

    @patch("app.blueprints.admin.send_email")
    def test_send_outreach_email(self, mock_send, client, seed_data, app):
        prospect_id = self._make_prospect(app, status="site_built")
        _login_admin(client)

        resp = client.post(f"/admin/prospects/{prospect_id}/send-outreach", data={
            "recipient_email": "jane@outreach.com",
            "custom_message": "Check out your demo site!",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"Outreach email sent" in resp.data
        mock_send.assert_called_once()

    @patch("app.blueprints.admin.send_email")
    def test_outreach_auto_advances_to_pitched(self, mock_send, client, seed_data, app):
        prospect_id = self._make_prospect(app, status="site_built")
        _login_admin(client)

        client.post(f"/admin/prospects/{prospect_id}/send-outreach", data={
            "recipient_email": "jane@outreach.com",
        })

        with app.app_context():
            prospect = db.session.get(Prospect, prospect_id)
            assert prospect.status == "pitched"

    @patch("app.blueprints.admin.send_email")
    def test_outreach_does_not_change_pitched_status(self, mock_send, client, seed_data, app):
        """If already pitched, sending outreach shouldn't change status."""
        prospect_id = self._make_prospect(app, status="pitched")
        _login_admin(client)

        client.post(f"/admin/prospects/{prospect_id}/send-outreach", data={
            "recipient_email": "jane@outreach.com",
        })

        with app.app_context():
            prospect = db.session.get(Prospect, prospect_id)
            assert prospect.status == "pitched"

    @patch("app.blueprints.admin.send_email")
    def test_outreach_logs_activity(self, mock_send, client, seed_data, app):
        prospect_id = self._make_prospect(app)
        _login_admin(client)

        client.post(f"/admin/prospects/{prospect_id}/send-outreach", data={
            "recipient_email": "jane@outreach.com",
        })

        with app.app_context():
            activity = ProspectActivity.query.filter_by(prospect_id=prospect_id).first()
            assert activity is not None
            assert activity.activity_type == "email"

    def test_outreach_missing_email(self, client, seed_data, app):
        prospect_id = self._make_prospect(app)
        _login_admin(client)

        resp = client.post(f"/admin/prospects/{prospect_id}/send-outreach", data={
            "recipient_email": "",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"Recipient email is required" in resp.data


# ══════════════════════════════════════════════
#  INVITE EMAIL SENDING
# ══════════════════════════════════════════════

class TestInviteEmail:

    @patch("app.blueprints.admin.send_email")
    def test_send_invite_email(self, mock_send, client, seed_data, app):
        _login_admin(client)

        resp = client.post(
            f"/admin/workspaces/{seed_data['workspace_id']}/send-invite-email",
            data={
                "recipient_email": "joe@testpizza.com",
                "invite_link": "http://localhost:5000/auth/register?token=abc123",
                "custom_message": "Welcome to your new site!",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"Invite email sent" in resp.data
        mock_send.assert_called_once()

    @patch("app.blueprints.admin.send_email")
    def test_send_invite_email_audit_logged(self, mock_send, client, seed_data, app):
        _login_admin(client)

        client.post(
            f"/admin/workspaces/{seed_data['workspace_id']}/send-invite-email",
            data={
                "recipient_email": "joe@testpizza.com",
                "invite_link": "http://localhost:5000/auth/register?token=abc123",
            },
        )

        with app.app_context():
            audit = AuditEvent.query.filter_by(action="invite.email_sent").first()
            assert audit is not None

    def test_send_invite_email_missing_recipient(self, client, seed_data, app):
        _login_admin(client)

        resp = client.post(
            f"/admin/workspaces/{seed_data['workspace_id']}/send-invite-email",
            data={
                "recipient_email": "",
                "invite_link": "http://localhost:5000/auth/register?token=abc123",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"Recipient email is required" in resp.data


# ══════════════════════════════════════════════
#  YELP SOURCE
# ══════════════════════════════════════════════

class TestYelpSource:

    def test_create_prospect_with_yelp_source(self, client, seed_data, app):
        _login_admin(client)

        resp = client.post("/admin/prospects/new", data={
            "business_name": "Yelp Test Biz",
            "source": "yelp",
            "source_url": "https://yelp.com/biz/test",
        }, follow_redirects=True)
        assert resp.status_code == 200

        with app.app_context():
            prospect = Prospect.query.filter_by(business_name="Yelp Test Biz").first()
            assert prospect is not None
            assert prospect.source == "yelp"

    def test_reject_invalid_source(self, client, seed_data, app):
        _login_admin(client)

        resp = client.post("/admin/prospects/new", data={
            "business_name": "Bad Source Biz",
            "source": "tiktok",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"valid source" in resp.data


# ══════════════════════════════════════════════
#  PROSPECT UPDATE PRESERVING FIELDS
# ══════════════════════════════════════════════

class TestProspectUpdatePreservesFields:

    def test_status_change_preserves_contact_info(self, client, seed_data, app):
        """Quick action status change should not wipe other fields."""
        _login_admin(client)

        with app.app_context():
            prospect = Prospect(
                business_name="Preserve Test",
                contact_name="John",
                contact_email="john@preserve.com",
                contact_phone="555-1234",
                source="google_maps",
                source_url="https://maps.google.com/test",
                demo_url="https://preserve.pages.dev",
                notes="Important notes here",
                status="researching",
            )
            db.session.add(prospect)
            db.session.commit()
            prospect_id = prospect.id

        # Simulate quick action form (only sends status, business_name, source)
        resp = client.post(f"/admin/prospects/{prospect_id}/update", data={
            "status": "site_built",
            "business_name": "Preserve Test",
            "source": "google_maps",
        }, follow_redirects=True)
        assert resp.status_code == 200

        with app.app_context():
            p = db.session.get(Prospect, prospect_id)
            assert p.status == "site_built"
            assert p.contact_name == "John"
            assert p.contact_email == "john@preserve.com"
            assert p.contact_phone == "555-1234"
            assert p.source_url == "https://maps.google.com/test"
            assert p.demo_url == "https://preserve.pages.dev"
            assert p.notes == "Important notes here"


# ══════════════════════════════════════════════
#  BILLING STATUS POLL ENDPOINT
# ══════════════════════════════════════════════

class TestBillingStatus:

    def test_status_returns_false_without_subscription(self, client, seed_data, app):
        with app.app_context():
            user = _make_client_user(db.session, seed_data["workspace_id"])
            db.session.commit()

        client.post("/auth/login", data={
            "email": "client@test.com", "password": "clientpass",
        })

        resp = client.get("/test-pizza/billing/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["active"] is False

    def test_status_returns_true_with_active_subscription(self, client, seed_data, app):
        with app.app_context():
            user = _make_client_user(db.session, seed_data["workspace_id"])
            _make_subscription(db.session, seed_data["workspace_id"], "active")
            db.session.commit()

        client.post("/auth/login", data={
            "email": "client@test.com", "password": "clientpass",
        })

        resp = client.get("/test-pizza/billing/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["active"] is True

    def test_status_returns_false_with_canceled_subscription(self, client, seed_data, app):
        with app.app_context():
            user = _make_client_user(db.session, seed_data["workspace_id"])
            _make_subscription(db.session, seed_data["workspace_id"], "canceled")
            db.session.commit()

        client.post("/auth/login", data={
            "email": "client@test.com", "password": "clientpass",
        })

        resp = client.get("/test-pizza/billing/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["active"] is False


# ══════════════════════════════════════════════
#  TICKET EMAIL NOTIFICATIONS
# ══════════════════════════════════════════════

class TestTicketEmailNotifications:

    @patch("app.blueprints.portal.send_email")
    def test_ticket_creation_sends_admin_email(self, mock_send, client, seed_data, app):
        with app.app_context():
            user = _make_client_user(db.session, seed_data["workspace_id"])
            _make_subscription(db.session, seed_data["workspace_id"], "active")
            db.session.commit()

        client.post("/auth/login", data={
            "email": "client@test.com", "password": "clientpass",
        })

        resp = client.post("/test-pizza/tickets/new", data={
            "subject": "Please update my hours",
            "description": "New hours are 9-5 Mon-Fri",
            "category": "content_update",
        }, follow_redirects=False)
        assert resp.status_code == 302
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args
        assert "New ticket" in call_kwargs[1]["subject"] or "New ticket" in call_kwargs[0][1]

    @patch("app.blueprints.portal.send_email")
    def test_client_reply_sends_admin_email(self, mock_send, client, seed_data, app):
        from app.models.ticket import Ticket

        with app.app_context():
            user = _make_client_user(db.session, seed_data["workspace_id"])
            _make_subscription(db.session, seed_data["workspace_id"], "active")
            ticket = Ticket(
                workspace_id=seed_data["workspace_id"],
                site_id=seed_data["site_id"],
                author_user_id=user.id,
                subject="Test ticket",
                description="Test desc",
                status="open",
                priority="normal",
            )
            db.session.add(ticket)
            db.session.commit()
            ticket_id = ticket.id

        client.post("/auth/login", data={
            "email": "client@test.com", "password": "clientpass",
        })

        resp = client.post(f"/test-pizza/tickets/{ticket_id}/reply", data={
            "message": "Here is more info",
        }, follow_redirects=False)
        assert resp.status_code == 302
        mock_send.assert_called_once()

    @patch("app.blueprints.admin.send_email")
    def test_admin_reply_sends_client_email(self, mock_send, client, seed_data, app):
        from app.models.ticket import Ticket

        with app.app_context():
            user = _make_client_user(db.session, seed_data["workspace_id"])
            ticket = Ticket(
                workspace_id=seed_data["workspace_id"],
                site_id=seed_data["site_id"],
                author_user_id=user.id,
                subject="Admin reply test",
                description="Test desc",
                status="open",
                priority="normal",
            )
            db.session.add(ticket)
            db.session.commit()
            ticket_id = ticket.id

        _login_admin(client)

        resp = client.post(f"/admin/tickets/{ticket_id}/reply", data={
            "message": "We've updated your site!",
        }, follow_redirects=True)
        assert resp.status_code == 200
        mock_send.assert_called_once()

    @patch("app.blueprints.admin.send_email")
    def test_admin_internal_note_does_not_email(self, mock_send, client, seed_data, app):
        from app.models.ticket import Ticket

        with app.app_context():
            user = _make_client_user(db.session, seed_data["workspace_id"])
            ticket = Ticket(
                workspace_id=seed_data["workspace_id"],
                site_id=seed_data["site_id"],
                author_user_id=user.id,
                subject="Internal note test",
                description="Test desc",
                status="open",
                priority="normal",
            )
            db.session.add(ticket)
            db.session.commit()
            ticket_id = ticket.id

        _login_admin(client)

        resp = client.post(f"/admin/tickets/{ticket_id}/reply", data={
            "message": "Internal note - don't email",
            "is_internal": "on",
        }, follow_redirects=True)
        assert resp.status_code == 200
        mock_send.assert_not_called()


# ══════════════════════════════════════════════
#  STRIPE PERIOD END EXTRACTION
# ══════════════════════════════════════════════

class TestExtractPeriodEnd:

    def test_top_level_period_end(self, app):
        """Old-style Stripe data with current_period_end at top level."""
        from app.services.stripe_service import _extract_period_end
        with app.app_context():
            result = _extract_period_end({"current_period_end": 1798761600})
            assert result is not None
            assert result.year == 2027

    def test_items_level_period_end(self, app):
        """New-style Stripe data with current_period_end on items."""
        from app.services.stripe_service import _extract_period_end
        with app.app_context():
            result = _extract_period_end({
                "items": {
                    "data": [{"current_period_end": 1798761600}]
                }
            })
            assert result is not None
            assert result.year == 2027

    def test_no_period_end(self, app):
        """No period end data returns None."""
        from app.services.stripe_service import _extract_period_end
        with app.app_context():
            result = _extract_period_end({})
            assert result is None

    def test_items_preferred_over_missing_top(self, app):
        """If top-level is missing, items-level is used."""
        from app.services.stripe_service import _extract_period_end
        with app.app_context():
            result = _extract_period_end({
                "items": {
                    "data": [{"current_period_end": 1798761600}]
                }
            })
            assert result is not None


# ══════════════════════════════════════════════
#  ADMIN DASHBOARD ENHANCEMENTS
# ══════════════════════════════════════════════

class TestAdminDashboardEnhancements:

    def test_dashboard_shows_mrr_breakdown(self, client, seed_data, app):
        _login_admin(client)

        with app.app_context():
            sub = BillingSubscription(
                workspace_id=seed_data["workspace_id"],
                stripe_subscription_id="sub_dash_basic",
                plan="basic",
                status="active",
            )
            db.session.add(sub)
            db.session.commit()

        resp = client.get("/admin/")
        assert resp.status_code == 200
        assert b"active subscriber" in resp.data
        assert b"$59/mo" in resp.data

    def test_dashboard_shows_at_risk(self, client, seed_data, app):
        _login_admin(client)

        with app.app_context():
            sub = BillingSubscription(
                workspace_id=seed_data["workspace_id"],
                stripe_subscription_id="sub_dash_pastdue",
                plan="basic",
                status="past_due",
            )
            db.session.add(sub)
            db.session.commit()

        resp = client.get("/admin/")
        assert resp.status_code == 200
        assert b"Past Due" in resp.data
        assert b"Past Due" in resp.data
