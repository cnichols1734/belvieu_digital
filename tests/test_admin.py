"""Tests for the admin blueprint — Phase 6.

Covers:
- Dashboard (metrics, pipeline counts)
- Prospects CRUD (list, new, detail, update, convert)
- Workspaces (list, detail, invite generation)
- Tickets (list, detail, reply with internal notes, status changes, assignment)
- Site status override
- Auth guards (non-admin rejected)
"""

import secrets
from datetime import datetime, timedelta, timezone

from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models.audit import AuditEvent
from app.models.billing import BillingCustomer, BillingSubscription
from app.models.invite import WorkspaceInvite
from app.models.prospect import Prospect
from app.models.site import Site
from app.models.ticket import Ticket, TicketMessage
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember, WorkspaceSettings


def login_admin(client, app):
    """Helper to log in as the admin user."""
    with app.app_context():
        admin = User.query.filter_by(email="admin@waas.local").first()
    return client.post(
        "/auth/login",
        data={"email": "admin@waas.local", "password": "admin123"},
        follow_redirects=True,
    )


def login_client_user(client, app):
    """Helper to create and log in as a non-admin user."""
    with app.app_context():
        user = User.query.filter_by(email="client@example.com").first()
        if not user:
            user = User(
                email="client@example.com",
                password_hash=generate_password_hash("client123"),
                full_name="Client User",
                is_admin=False,
            )
            db.session.add(user)
            db.session.commit()
    return client.post(
        "/auth/login",
        data={"email": "client@example.com", "password": "client123"},
        follow_redirects=True,
    )


# ══════════════════════════════════════════════
#  AUTH GUARDS
# ══════════════════════════════════════════════

class TestAdminAuthGuards:
    """Verify non-admin users are rejected from all admin routes."""

    def test_unauthenticated_redirects_to_login(self, client, seed_data):
        """Unauthenticated user is redirected to login."""
        resp = client.get("/admin/")
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]

    def test_non_admin_gets_403(self, client, app, seed_data):
        """Non-admin user gets 403 on admin routes."""
        login_client_user(client, app)
        resp = client.get("/admin/")
        assert resp.status_code == 403

    def test_non_admin_cannot_access_prospects(self, client, app, seed_data):
        login_client_user(client, app)
        resp = client.get("/admin/prospects")
        assert resp.status_code == 403

    def test_non_admin_cannot_access_workspaces(self, client, app, seed_data):
        login_client_user(client, app)
        resp = client.get("/admin/workspaces")
        assert resp.status_code == 403

    def test_non_admin_cannot_access_tickets(self, client, app, seed_data):
        login_client_user(client, app)
        resp = client.get("/admin/tickets")
        assert resp.status_code == 403


# ══════════════════════════════════════════════
#  DASHBOARD
# ══════════════════════════════════════════════

class TestAdminDashboard:
    def test_dashboard_loads(self, client, app, seed_data):
        """Dashboard renders with metrics."""
        login_admin(client, app)
        resp = client.get("/admin/")
        assert resp.status_code == 200
        assert b"Admin Dashboard" in resp.data

    def test_dashboard_shows_pipeline_counts(self, client, app, seed_data):
        """Dashboard shows prospect pipeline counts."""
        login_admin(client, app)
        resp = client.get("/admin/")
        assert resp.status_code == 200
        # The seed data has 1 converted prospect
        assert b"Converted" in resp.data

    def test_dashboard_shows_mrr(self, client, app, seed_data):
        """Dashboard shows MRR from active subscriptions."""
        # Create an active subscription
        with app.app_context():
            ws = Workspace.query.first()
            bc = BillingCustomer(
                workspace_id=ws.id,
                stripe_customer_id="cus_test_dashboard",
            )
            db.session.add(bc)
            sub = BillingSubscription(
                workspace_id=ws.id,
                stripe_subscription_id="sub_test_dashboard",
                stripe_price_id="price_test",
                plan="basic",
                status="active",
            )
            db.session.add(sub)
            db.session.commit()

        login_admin(client, app)
        resp = client.get("/admin/")
        assert resp.status_code == 200
        assert b"$59" in resp.data  # MRR from basic plan


# ══════════════════════════════════════════════
#  PROSPECTS
# ══════════════════════════════════════════════

class TestAdminProspects:
    def test_prospect_list_loads(self, client, app, seed_data):
        login_admin(client, app)
        resp = client.get("/admin/prospects")
        assert resp.status_code == 200
        assert b"Prospects" in resp.data
        assert b"Test Pizza Shop" in resp.data

    def test_prospect_list_filter_by_status(self, client, app, seed_data):
        login_admin(client, app)
        resp = client.get("/admin/prospects?status=converted")
        assert resp.status_code == 200
        assert b"Test Pizza Shop" in resp.data

    def test_prospect_list_filter_empty_result(self, client, app, seed_data):
        login_admin(client, app)
        resp = client.get("/admin/prospects?status=declined")
        assert resp.status_code == 200
        assert b"No prospects" in resp.data

    def test_prospect_new_form_loads(self, client, app, seed_data):
        login_admin(client, app)
        resp = client.get("/admin/prospects/new")
        assert resp.status_code == 200
        assert b"Add New Prospect" in resp.data

    def test_prospect_create_success(self, client, app, seed_data):
        login_admin(client, app)
        resp = client.post(
            "/admin/prospects/new",
            data={
                "business_name": "Joe's Tacos",
                "contact_name": "Joe Taco",
                "contact_email": "joe@tacos.com",
                "source": "google_maps",
                "notes": "Great taco place, no website",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"Joe&#39;s Tacos" in resp.data or b"Joe's Tacos" in resp.data

        # Verify in DB
        with app.app_context():
            p = Prospect.query.filter_by(business_name="Joe's Tacos").first()
            assert p is not None
            assert p.status == "researching"
            assert p.source == "google_maps"

    def test_prospect_create_missing_name(self, client, app, seed_data):
        login_admin(client, app)
        resp = client.post(
            "/admin/prospects/new",
            data={"business_name": "", "source": "google_maps"},
        )
        assert resp.status_code == 200
        assert b"Business name is required" in resp.data

    def test_prospect_create_invalid_source(self, client, app, seed_data):
        login_admin(client, app)
        resp = client.post(
            "/admin/prospects/new",
            data={"business_name": "Test Biz", "source": "invalid_source"},
        )
        assert resp.status_code == 200
        assert b"valid source" in resp.data

    def test_prospect_detail_loads(self, client, app, seed_data):
        login_admin(client, app)
        with app.app_context():
            prospect = Prospect.query.first()
            prospect_id = prospect.id
        # Converted prospects redirect to workspace detail page
        resp = client.get(f"/admin/prospects/{prospect_id}", follow_redirects=True)
        assert resp.status_code == 200
        assert b"Test Pizza Shop" in resp.data

    def test_prospect_detail_not_found(self, client, app, seed_data):
        login_admin(client, app)
        resp = client.get("/admin/prospects/nonexistent-id", follow_redirects=True)
        assert resp.status_code == 200
        assert b"Prospect not found" in resp.data

    def test_prospect_update(self, client, app, seed_data):
        login_admin(client, app)
        with app.app_context():
            prospect = Prospect.query.first()
            prospect_id = prospect.id
        resp = client.post(
            f"/admin/prospects/{prospect_id}/update",
            data={
                "business_name": "Updated Pizza",
                "source": "facebook",
                "status": "pitched",
                "notes": "Pitched them via email",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"Prospect updated" in resp.data

        with app.app_context():
            p = db.session.get(Prospect, prospect_id)
            assert p.business_name == "Updated Pizza"
            assert p.source == "facebook"

    def test_prospect_convert_form_loads(self, client, app, seed_data):
        """Create a non-converted prospect and load the convert form."""
        with app.app_context():
            prospect = Prospect(
                business_name="Convert Me Burgers",
                contact_email="owner@burgers.com",
                source="google_maps",
                status="pitched",
            )
            db.session.add(prospect)
            db.session.commit()
            prospect_id = prospect.id

        login_admin(client, app)
        resp = client.get(f"/admin/prospects/{prospect_id}/convert")
        assert resp.status_code == 200
        assert b"Convert to Client" in resp.data
        assert b"Convert Me Burgers" in resp.data

    def test_prospect_convert_success(self, client, app, seed_data):
        """Full conversion: creates workspace + site + invite."""
        with app.app_context():
            prospect = Prospect(
                business_name="Success Burger",
                contact_email="owner@successburger.com",
                source="google_maps",
                demo_url="https://successburger.example.dev",
                status="pitched",
            )
            db.session.add(prospect)
            db.session.commit()
            prospect_id = prospect.id

        login_admin(client, app)
        resp = client.post(
            f"/admin/prospects/{prospect_id}/convert",
            data={
                "site_slug": "success-burger",
                "display_name": "Success Burger",
                "published_url": "https://successburger.example.dev",
                "invite_email": "owner@successburger.com",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"Client Created Successfully" in resp.data
        assert b"success-burger" in resp.data

        # Verify in DB
        with app.app_context():
            p = db.session.get(Prospect, prospect_id)
            assert p.status == "converted"
            assert p.workspace_id is not None

            ws = db.session.get(Workspace, p.workspace_id)
            assert ws is not None
            assert ws.name == "Success Burger"

            site = Site.query.filter_by(site_slug="success-burger").first()
            assert site is not None
            assert site.workspace_id == ws.id

            invite = WorkspaceInvite.query.filter_by(workspace_id=ws.id).first()
            assert invite is not None
            assert invite.email == "owner@successburger.com"

    def test_prospect_convert_duplicate_slug(self, client, app, seed_data):
        """Duplicate slug is rejected."""
        with app.app_context():
            prospect = Prospect(
                business_name="Dupe Slug Place",
                source="google_maps",
                status="pitched",
            )
            db.session.add(prospect)
            db.session.commit()
            prospect_id = prospect.id

        login_admin(client, app)
        # "test-pizza" slug already exists from seed_data
        resp = client.post(
            f"/admin/prospects/{prospect_id}/convert",
            data={
                "site_slug": "test-pizza",
                "display_name": "Dupe Slug Place",
            },
        )
        assert resp.status_code == 200
        assert b"already taken" in resp.data

    def test_prospect_convert_already_converted(self, client, app, seed_data):
        """Already-converted prospect redirects with warning."""
        login_admin(client, app)
        with app.app_context():
            prospect = Prospect.query.filter_by(status="converted").first()
            prospect_id = prospect.id
        resp = client.get(f"/admin/prospects/{prospect_id}/convert", follow_redirects=True)
        assert resp.status_code == 200
        assert b"already been converted" in resp.data


# ══════════════════════════════════════════════
#  WORKSPACES
# ══════════════════════════════════════════════

class TestAdminWorkspaces:
    def test_workspace_list_loads(self, client, app, seed_data):
        login_admin(client, app)
        resp = client.get("/admin/workspaces")
        assert resp.status_code == 200
        assert b"Workspaces" in resp.data
        assert b"Test Pizza Shop" in resp.data

    def test_workspace_detail_loads(self, client, app, seed_data):
        login_admin(client, app)
        ws_id = seed_data["workspace_id"]
        resp = client.get(f"/admin/workspaces/{ws_id}")
        assert resp.status_code == 200
        assert b"Test Pizza Shop" in resp.data
        assert b"test-pizza" in resp.data

    def test_workspace_detail_not_found(self, client, app, seed_data):
        login_admin(client, app)
        resp = client.get("/admin/workspaces/nonexistent-id", follow_redirects=True)
        assert resp.status_code == 200
        assert b"Workspace not found" in resp.data

    def test_workspace_detail_shows_members(self, client, app, seed_data):
        login_admin(client, app)
        ws_id = seed_data["workspace_id"]
        resp = client.get(f"/admin/workspaces/{ws_id}")
        assert resp.status_code == 200
        assert b"admin@waas.local" in resp.data

    def test_workspace_detail_shows_invites(self, client, app, seed_data):
        login_admin(client, app)
        ws_id = seed_data["workspace_id"]
        resp = client.get(f"/admin/workspaces/{ws_id}")
        assert resp.status_code == 200
        # Seed data has multiple invites
        assert b"Invite History" in resp.data

    def test_workspace_generate_invite(self, client, app, seed_data):
        login_admin(client, app)
        ws_id = seed_data["workspace_id"]
        resp = client.post(
            f"/admin/workspaces/{ws_id}/invite",
            data={"invite_email": "newinvite@example.com"},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"Invite Link Generated" in resp.data
        assert b"newinvite@example.com" in resp.data

        # Verify in DB
        with app.app_context():
            invite = WorkspaceInvite.query.filter_by(
                workspace_id=ws_id, email="newinvite@example.com"
            ).first()
            assert invite is not None
            assert invite.is_valid

    def test_workspace_generate_open_invite(self, client, app, seed_data):
        login_admin(client, app)
        ws_id = seed_data["workspace_id"]
        resp = client.post(
            f"/admin/workspaces/{ws_id}/invite",
            data={"invite_email": ""},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"Invite Link Generated" in resp.data
        assert b"any email can use this link" in resp.data


# ══════════════════════════════════════════════
#  TICKETS
# ══════════════════════════════════════════════

class TestAdminTickets:
    def _create_ticket(self, app, seed_data):
        """Helper to create a test ticket."""
        with app.app_context():
            ticket = Ticket(
                workspace_id=seed_data["workspace_id"],
                site_id=seed_data["site_id"],
                author_user_id=seed_data["admin_id"],
                subject="Test Ticket",
                description="Test ticket description",
                category="bug",
                status="open",
                priority="normal",
            )
            db.session.add(ticket)
            db.session.commit()
            return ticket.id

    def test_ticket_list_loads(self, client, app, seed_data):
        self._create_ticket(app, seed_data)
        login_admin(client, app)
        resp = client.get("/admin/tickets")
        assert resp.status_code == 200
        assert b"All Tickets" in resp.data
        assert b"Test Ticket" in resp.data

    def test_ticket_list_filter_by_status(self, client, app, seed_data):
        self._create_ticket(app, seed_data)
        login_admin(client, app)
        resp = client.get("/admin/tickets?status=open")
        assert resp.status_code == 200
        assert b"Test Ticket" in resp.data

    def test_ticket_list_filter_unassigned(self, client, app, seed_data):
        self._create_ticket(app, seed_data)
        login_admin(client, app)
        resp = client.get("/admin/tickets?assignee=unassigned")
        assert resp.status_code == 200
        assert b"Test Ticket" in resp.data

    def test_ticket_detail_loads(self, client, app, seed_data):
        ticket_id = self._create_ticket(app, seed_data)
        login_admin(client, app)
        resp = client.get(f"/admin/tickets/{ticket_id}")
        assert resp.status_code == 200
        assert b"Test Ticket" in resp.data
        assert b"Test ticket description" in resp.data

    def test_ticket_detail_shows_internal_notes(self, client, app, seed_data):
        """Admin view shows internal notes (unlike client view)."""
        ticket_id = self._create_ticket(app, seed_data)
        with app.app_context():
            msg = TicketMessage(
                ticket_id=ticket_id,
                author_user_id=seed_data["admin_id"],
                message="This is an internal note",
                is_internal=True,
            )
            db.session.add(msg)
            db.session.commit()

        login_admin(client, app)
        resp = client.get(f"/admin/tickets/{ticket_id}")
        assert resp.status_code == 200
        assert b"This is an internal note" in resp.data
        assert b"Internal" in resp.data

    def test_ticket_detail_not_found(self, client, app, seed_data):
        login_admin(client, app)
        resp = client.get("/admin/tickets/nonexistent-id", follow_redirects=True)
        assert resp.status_code == 200
        assert b"Ticket not found" in resp.data

    def test_ticket_reply(self, client, app, seed_data):
        ticket_id = self._create_ticket(app, seed_data)
        login_admin(client, app)
        resp = client.post(
            f"/admin/tickets/{ticket_id}/reply",
            data={"message": "Admin reply here"},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"Reply sent" in resp.data

        # Verify in DB
        with app.app_context():
            msg = TicketMessage.query.filter_by(
                ticket_id=ticket_id, is_internal=False
            ).first()
            assert msg is not None
            assert "Admin reply here" in msg.message

    def test_ticket_reply_internal(self, client, app, seed_data):
        ticket_id = self._create_ticket(app, seed_data)
        login_admin(client, app)
        resp = client.post(
            f"/admin/tickets/{ticket_id}/reply",
            data={"message": "Internal note here", "is_internal": "on"},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"Internal note added" in resp.data

        with app.app_context():
            msg = TicketMessage.query.filter_by(
                ticket_id=ticket_id, is_internal=True
            ).first()
            assert msg is not None
            assert "Internal note here" in msg.message

    def test_ticket_reply_empty(self, client, app, seed_data):
        ticket_id = self._create_ticket(app, seed_data)
        login_admin(client, app)
        resp = client.post(
            f"/admin/tickets/{ticket_id}/reply",
            data={"message": ""},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"Reply cannot be empty" in resp.data

    def test_ticket_status_change(self, client, app, seed_data):
        ticket_id = self._create_ticket(app, seed_data)
        login_admin(client, app)
        resp = client.post(
            f"/admin/tickets/{ticket_id}/status",
            data={"status": "in_progress"},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"Status changed" in resp.data

        with app.app_context():
            ticket = db.session.get(Ticket, ticket_id)
            assert ticket.status == "in_progress"

    def test_ticket_invalid_status_change(self, client, app, seed_data):
        ticket_id = self._create_ticket(app, seed_data)
        login_admin(client, app)
        # Can't go from 'open' to 'waiting_on_client' directly
        resp = client.post(
            f"/admin/tickets/{ticket_id}/status",
            data={"status": "waiting_on_client"},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"Cannot transition" in resp.data

    def test_ticket_assign(self, client, app, seed_data):
        ticket_id = self._create_ticket(app, seed_data)
        admin_id = seed_data["admin_id"]
        login_admin(client, app)
        resp = client.post(
            f"/admin/tickets/{ticket_id}/assign",
            data={"assigned_to": admin_id},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"Ticket assigned" in resp.data

        with app.app_context():
            ticket = db.session.get(Ticket, ticket_id)
            assert ticket.assigned_to_user_id == admin_id

    def test_ticket_unassign(self, client, app, seed_data):
        ticket_id = self._create_ticket(app, seed_data)
        admin_id = seed_data["admin_id"]
        # First assign
        with app.app_context():
            ticket = db.session.get(Ticket, ticket_id)
            ticket.assigned_to_user_id = admin_id
            db.session.commit()

        login_admin(client, app)
        resp = client.post(
            f"/admin/tickets/{ticket_id}/assign",
            data={"assigned_to": ""},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"Ticket unassigned" in resp.data


# ══════════════════════════════════════════════
#  SITE STATUS OVERRIDE
# ══════════════════════════════════════════════

class TestAdminSiteOverride:
    def test_site_status_override(self, client, app, seed_data):
        login_admin(client, app)
        site_id = seed_data["site_id"]
        resp = client.post(
            f"/admin/sites/{site_id}/status",
            data={"status": "active"},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"Site status changed" in resp.data

        with app.app_context():
            site = db.session.get(Site, site_id)
            assert site.status == "active"

    def test_site_status_invalid(self, client, app, seed_data):
        login_admin(client, app)
        site_id = seed_data["site_id"]
        resp = client.post(
            f"/admin/sites/{site_id}/status",
            data={"status": "invalid_status"},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"Invalid site status" in resp.data

    def test_site_not_found(self, client, app, seed_data):
        login_admin(client, app)
        resp = client.post(
            "/admin/sites/nonexistent-id/status",
            data={"status": "active"},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"Site not found" in resp.data
