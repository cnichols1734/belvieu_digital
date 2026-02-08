"""Tests for Phase 5: Ticketing System.

Covers:
- Ticket creation (portal route + service)
- Ticket listing with status filters
- Ticket detail view (client-side, internal notes hidden)
- Ticket reply + auto-transition from waiting_on_client
- Access gating (full vs read_only vs blocked vs subscribe)
- Workspace isolation (cross-tenant access denied)
- Status transitions (valid + invalid)
- Input sanitization via bleach
- Assignment validation
"""

import pytest
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember, WorkspaceSettings
from app.models.site import Site
from app.models.billing import BillingSubscription
from app.models.ticket import Ticket, TicketMessage
from app.services import ticket_service


# ─── Helpers ───────────────────────────────────────────────

def _login(client, email, password):
    """Log in a user via the auth form."""
    return client.post("/auth/login", data={
        "email": email,
        "password": password,
    }, follow_redirects=False)


def _make_client_user(db_session, workspace_id):
    """Create a non-admin client user with workspace membership."""
    user = User(
        email="client@testpizza.com",
        password_hash=generate_password_hash("clientpass"),
        full_name="Client User",
        is_admin=False,
    )
    db_session.add(user)
    db_session.flush()

    membership = WorkspaceMember(
        user_id=user.id,
        workspace_id=workspace_id,
        role="owner",
    )
    db_session.add(membership)
    db_session.flush()
    return user


def _make_subscription(db_session, workspace_id, status="active"):
    """Create a billing subscription for a workspace."""
    sub = BillingSubscription(
        workspace_id=workspace_id,
        stripe_subscription_id=f"sub_test_{status}",
        stripe_price_id="price_test",
        plan="basic",
        status=status,
    )
    db_session.add(sub)
    db_session.flush()
    return sub


def _make_ticket(db_session, workspace_id, site_id, author_id, **kwargs):
    """Create a ticket directly in the DB."""
    defaults = {
        "subject": "Test ticket",
        "description": "Test description",
        "category": "question",
        "status": "open",
        "priority": "normal",
    }
    defaults.update(kwargs)
    ticket = Ticket(
        workspace_id=workspace_id,
        site_id=site_id,
        author_user_id=author_id,
        **defaults,
    )
    db_session.add(ticket)
    db_session.flush()
    return ticket


# ─── Ticket Service Tests ──────────────────────────────────

class TestTicketService:
    """Tests for ticket_service.py functions."""

    def test_create_ticket(self, app, seed_data):
        with app.app_context():
            ticket = ticket_service.create_ticket(
                workspace_id=seed_data["workspace_id"],
                site_id=seed_data["site_id"],
                user_id=seed_data["admin_id"],
                subject="Need help",
                description="My site is broken",
                category="bug",
            )
            db.session.commit()
            assert ticket.id is not None
            assert ticket.subject == "Need help"
            assert ticket.status == "open"
            assert ticket.priority == "normal"
            assert ticket.category == "bug"

    def test_create_ticket_sanitizes_html(self, app, seed_data):
        with app.app_context():
            ticket = ticket_service.create_ticket(
                workspace_id=seed_data["workspace_id"],
                site_id=seed_data["site_id"],
                user_id=seed_data["admin_id"],
                subject="<script>alert('xss')</script>Help",
                description="<b>Bold</b> text <img src=x onerror=alert(1)>",
                category="question",
            )
            db.session.commit()
            assert "<script>" not in ticket.subject
            assert "alert('xss')" in ticket.subject  # text is kept, tags stripped
            assert "<b>" not in ticket.description
            assert "Bold" in ticket.description

    def test_create_ticket_invalid_category(self, app, seed_data):
        with app.app_context():
            with pytest.raises(ValueError, match="Invalid category"):
                ticket_service.create_ticket(
                    workspace_id=seed_data["workspace_id"],
                    site_id=seed_data["site_id"],
                    user_id=seed_data["admin_id"],
                    subject="Test",
                    description="Test",
                    category="invalid_cat",
                )

    def test_create_ticket_empty_subject(self, app, seed_data):
        with app.app_context():
            with pytest.raises(ValueError, match="Subject is required"):
                ticket_service.create_ticket(
                    workspace_id=seed_data["workspace_id"],
                    site_id=seed_data["site_id"],
                    user_id=seed_data["admin_id"],
                    subject="",
                    description="Test",
                )

    def test_add_message(self, app, seed_data):
        with app.app_context():
            ticket = _make_ticket(
                db.session, seed_data["workspace_id"],
                seed_data["site_id"], seed_data["admin_id"],
            )
            db.session.commit()

            msg = ticket_service.add_message(
                ticket_id=ticket.id,
                user_id=seed_data["admin_id"],
                message="Here's an update",
            )
            db.session.commit()
            assert msg.message == "Here's an update"
            assert msg.is_internal is False

    def test_add_message_sanitizes_html(self, app, seed_data):
        with app.app_context():
            ticket = _make_ticket(
                db.session, seed_data["workspace_id"],
                seed_data["site_id"], seed_data["admin_id"],
            )
            db.session.commit()

            msg = ticket_service.add_message(
                ticket_id=ticket.id,
                user_id=seed_data["admin_id"],
                message="<script>alert('xss')</script>Hello",
            )
            db.session.commit()
            assert "<script>" not in msg.message
            assert "Hello" in msg.message

    def test_add_message_internal(self, app, seed_data):
        with app.app_context():
            ticket = _make_ticket(
                db.session, seed_data["workspace_id"],
                seed_data["site_id"], seed_data["admin_id"],
            )
            db.session.commit()

            msg = ticket_service.add_message(
                ticket_id=ticket.id,
                user_id=seed_data["admin_id"],
                message="Internal note",
                is_internal=True,
            )
            db.session.commit()
            assert msg.is_internal is True

    def test_auto_transition_waiting_to_in_progress_on_client_reply(self, app, seed_data):
        """Client reply on a waiting_on_client ticket auto-transitions to in_progress."""
        with app.app_context():
            client_user = _make_client_user(db.session, seed_data["workspace_id"])
            ticket = _make_ticket(
                db.session, seed_data["workspace_id"],
                seed_data["site_id"], client_user.id,
                status="waiting_on_client",
            )
            db.session.commit()

            ticket_service.add_message(
                ticket_id=ticket.id,
                user_id=client_user.id,
                message="Here's the info you requested",
            )
            db.session.commit()

            updated = db.session.get(Ticket, ticket.id)
            assert updated.status == "in_progress"

    def test_no_auto_transition_on_admin_reply(self, app, seed_data):
        """Admin reply on waiting_on_client does NOT auto-transition."""
        with app.app_context():
            ticket = _make_ticket(
                db.session, seed_data["workspace_id"],
                seed_data["site_id"], seed_data["admin_id"],
                status="waiting_on_client",
            )
            db.session.commit()

            ticket_service.add_message(
                ticket_id=ticket.id,
                user_id=seed_data["admin_id"],
                message="Admin follow-up",
            )
            db.session.commit()

            updated = db.session.get(Ticket, ticket.id)
            assert updated.status == "waiting_on_client"

    def test_update_status_valid(self, app, seed_data):
        with app.app_context():
            ticket = _make_ticket(
                db.session, seed_data["workspace_id"],
                seed_data["site_id"], seed_data["admin_id"],
            )
            db.session.commit()

            ticket_service.update_status(ticket.id, "in_progress", seed_data["admin_id"])
            db.session.commit()
            assert db.session.get(Ticket, ticket.id).status == "in_progress"

    def test_update_status_invalid_transition(self, app, seed_data):
        """Cannot go from 'open' directly to 'waiting_on_client'."""
        with app.app_context():
            ticket = _make_ticket(
                db.session, seed_data["workspace_id"],
                seed_data["site_id"], seed_data["admin_id"],
            )
            db.session.commit()

            with pytest.raises(ValueError, match="Cannot transition"):
                ticket_service.update_status(ticket.id, "waiting_on_client", seed_data["admin_id"])

    def test_update_status_done_is_terminal(self, app, seed_data):
        """Cannot transition from 'done' to anything."""
        with app.app_context():
            ticket = _make_ticket(
                db.session, seed_data["workspace_id"],
                seed_data["site_id"], seed_data["admin_id"],
                status="done",
            )
            db.session.commit()

            with pytest.raises(ValueError, match="Cannot transition"):
                ticket_service.update_status(ticket.id, "open", seed_data["admin_id"])

    def test_assign_ticket_to_admin(self, app, seed_data):
        with app.app_context():
            ticket = _make_ticket(
                db.session, seed_data["workspace_id"],
                seed_data["site_id"], seed_data["admin_id"],
            )
            db.session.commit()

            ticket_service.assign_ticket(ticket.id, seed_data["admin_id"], seed_data["admin_id"])
            db.session.commit()
            assert db.session.get(Ticket, ticket.id).assigned_to_user_id == seed_data["admin_id"]

    def test_assign_ticket_to_non_admin_fails(self, app, seed_data):
        with app.app_context():
            client_user = _make_client_user(db.session, seed_data["workspace_id"])
            ticket = _make_ticket(
                db.session, seed_data["workspace_id"],
                seed_data["site_id"], seed_data["admin_id"],
            )
            db.session.commit()

            with pytest.raises(ValueError, match="admin"):
                ticket_service.assign_ticket(ticket.id, client_user.id, seed_data["admin_id"])

    def test_get_ticket_with_messages_excludes_internal(self, app, seed_data):
        with app.app_context():
            ticket = _make_ticket(
                db.session, seed_data["workspace_id"],
                seed_data["site_id"], seed_data["admin_id"],
            )
            # Add public + internal message
            msg1 = TicketMessage(
                ticket_id=ticket.id,
                author_user_id=seed_data["admin_id"],
                message="Public reply",
                is_internal=False,
            )
            msg2 = TicketMessage(
                ticket_id=ticket.id,
                author_user_id=seed_data["admin_id"],
                message="Secret internal note",
                is_internal=True,
            )
            db.session.add_all([msg1, msg2])
            db.session.commit()

            _, messages = ticket_service.get_ticket_with_messages(ticket.id, include_internal=False)
            assert len(messages) == 1
            assert messages[0].message == "Public reply"

            _, all_messages = ticket_service.get_ticket_with_messages(ticket.id, include_internal=True)
            assert len(all_messages) == 2

    def test_list_tickets_with_status_filter(self, app, seed_data):
        with app.app_context():
            _make_ticket(db.session, seed_data["workspace_id"],
                         seed_data["site_id"], seed_data["admin_id"],
                         subject="Open ticket", status="open")
            _make_ticket(db.session, seed_data["workspace_id"],
                         seed_data["site_id"], seed_data["admin_id"],
                         subject="Done ticket", status="done")
            db.session.commit()

            all_tickets = ticket_service.list_tickets_for_workspace(seed_data["workspace_id"])
            assert len(all_tickets) == 2

            open_only = ticket_service.list_tickets_for_workspace(seed_data["workspace_id"], status_filter="open")
            assert len(open_only) == 1
            assert open_only[0].subject == "Open ticket"


# ─── Portal Route Tests ───────────────────────────────────

class TestTicketRoutes:
    """Tests for ticket-related portal routes."""

    def test_ticket_list_requires_auth(self, client, seed_data):
        resp = client.get("/test-pizza/tickets")
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]

    def test_ticket_list_with_active_sub(self, app, client, seed_data):
        with app.app_context():
            user = _make_client_user(db.session, seed_data["workspace_id"])
            _make_subscription(db.session, seed_data["workspace_id"], "active")
            _make_ticket(db.session, seed_data["workspace_id"],
                         seed_data["site_id"], user.id,
                         subject="My ticket")
            db.session.commit()
            user_email = user.email

        _login(client, user_email, "clientpass")
        resp = client.get("/test-pizza/tickets")
        assert resp.status_code == 200
        assert b"My ticket" in resp.data

    def test_ticket_list_blocked_can_still_view(self, app, client, seed_data):
        """Clients with blocked access can still view ticket list."""
        with app.app_context():
            user = _make_client_user(db.session, seed_data["workspace_id"])
            _make_subscription(db.session, seed_data["workspace_id"], "canceled")
            _make_ticket(db.session, seed_data["workspace_id"],
                         seed_data["site_id"], user.id,
                         subject="Old ticket")
            db.session.commit()
            user_email = user.email

        _login(client, user_email, "clientpass")
        resp = client.get("/test-pizza/tickets")
        assert resp.status_code == 200
        assert b"Old ticket" in resp.data

    def test_ticket_list_with_status_filter(self, app, client, seed_data):
        with app.app_context():
            user = _make_client_user(db.session, seed_data["workspace_id"])
            _make_subscription(db.session, seed_data["workspace_id"], "active")
            _make_ticket(db.session, seed_data["workspace_id"],
                         seed_data["site_id"], user.id,
                         subject="Open one", status="open")
            _make_ticket(db.session, seed_data["workspace_id"],
                         seed_data["site_id"], user.id,
                         subject="Done one", status="done")
            db.session.commit()
            user_email = user.email

        _login(client, user_email, "clientpass")
        resp = client.get("/test-pizza/tickets?status=open")
        assert resp.status_code == 200
        assert b"Open one" in resp.data
        assert b"Done one" not in resp.data

    def test_create_ticket_page_loads(self, app, client, seed_data):
        with app.app_context():
            user = _make_client_user(db.session, seed_data["workspace_id"])
            _make_subscription(db.session, seed_data["workspace_id"], "active")
            db.session.commit()
            user_email = user.email

        _login(client, user_email, "clientpass")
        resp = client.get("/test-pizza/tickets/new")
        assert resp.status_code == 200
        assert b"Create a ticket" in resp.data

    def test_create_ticket_submit(self, app, client, seed_data):
        with app.app_context():
            user = _make_client_user(db.session, seed_data["workspace_id"])
            _make_subscription(db.session, seed_data["workspace_id"], "active")
            db.session.commit()
            user_email = user.email

        _login(client, user_email, "clientpass")
        resp = client.post("/test-pizza/tickets/new", data={
            "subject": "Update my hours",
            "description": "Please change hours to 9-5",
            "category": "content_update",
        }, follow_redirects=False)
        assert resp.status_code == 302

        # Verify ticket was created
        with app.app_context():
            ticket = Ticket.query.filter_by(subject="Update my hours").first()
            assert ticket is not None
            assert ticket.category == "content_update"
            assert ticket.status == "open"

    def test_create_ticket_missing_fields(self, app, client, seed_data):
        with app.app_context():
            user = _make_client_user(db.session, seed_data["workspace_id"])
            _make_subscription(db.session, seed_data["workspace_id"], "active")
            db.session.commit()
            user_email = user.email

        _login(client, user_email, "clientpass")
        resp = client.post("/test-pizza/tickets/new", data={
            "subject": "",
            "description": "",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"required" in resp.data

    def test_create_ticket_blocked_redirects(self, app, client, seed_data):
        """Blocked users cannot create tickets — redirected to ticket list."""
        with app.app_context():
            user = _make_client_user(db.session, seed_data["workspace_id"])
            _make_subscription(db.session, seed_data["workspace_id"], "canceled")
            db.session.commit()
            user_email = user.email

        _login(client, user_email, "clientpass")
        resp = client.get("/test-pizza/tickets/new")
        assert resp.status_code == 302
        assert "/tickets" in resp.headers["Location"]

    def test_create_ticket_no_sub_redirects(self, app, client, seed_data):
        """Users without subscription cannot create tickets."""
        with app.app_context():
            user = _make_client_user(db.session, seed_data["workspace_id"])
            db.session.commit()
            user_email = user.email

        _login(client, user_email, "clientpass")
        # With no subscription, dashboard would show subscribe page, but
        # ticket_new checks access_level directly
        resp = client.get("/test-pizza/tickets/new")
        assert resp.status_code == 302

    def test_ticket_detail_view(self, app, client, seed_data):
        with app.app_context():
            user = _make_client_user(db.session, seed_data["workspace_id"])
            _make_subscription(db.session, seed_data["workspace_id"], "active")
            ticket = _make_ticket(
                db.session, seed_data["workspace_id"],
                seed_data["site_id"], user.id,
                subject="Detail test",
            )
            db.session.commit()
            user_email = user.email
            ticket_id = ticket.id

        _login(client, user_email, "clientpass")
        resp = client.get(f"/test-pizza/tickets/{ticket_id}")
        assert resp.status_code == 200
        assert b"Detail test" in resp.data

    def test_ticket_detail_hides_internal_notes(self, app, client, seed_data):
        """Internal notes should not be visible to clients."""
        with app.app_context():
            user = _make_client_user(db.session, seed_data["workspace_id"])
            _make_subscription(db.session, seed_data["workspace_id"], "active")
            ticket = _make_ticket(
                db.session, seed_data["workspace_id"],
                seed_data["site_id"], user.id,
                subject="Notes test",
            )
            # Add public and internal messages
            public_msg = TicketMessage(
                ticket_id=ticket.id,
                author_user_id=seed_data["admin_id"],
                message="Public reply here",
                is_internal=False,
            )
            internal_msg = TicketMessage(
                ticket_id=ticket.id,
                author_user_id=seed_data["admin_id"],
                message="Secret admin note",
                is_internal=True,
            )
            db.session.add_all([public_msg, internal_msg])
            db.session.commit()
            user_email = user.email
            ticket_id = ticket.id

        _login(client, user_email, "clientpass")
        resp = client.get(f"/test-pizza/tickets/{ticket_id}")
        assert resp.status_code == 200
        assert b"Public reply here" in resp.data
        assert b"Secret admin note" not in resp.data

    def test_ticket_detail_wrong_workspace(self, app, client, seed_data):
        """Cannot view a ticket from another workspace."""
        with app.app_context():
            # Create a second workspace + site
            workspace2 = Workspace(name="Other Business")
            db.session.add(workspace2)
            db.session.flush()

            site2 = Site(
                workspace_id=workspace2.id,
                site_slug="other-biz",
                display_name="Other Business",
                status="demo",
            )
            db.session.add(site2)
            db.session.flush()

            # Ticket belongs to workspace2
            other_ticket = _make_ticket(
                db.session, workspace2.id,
                site2.id, seed_data["admin_id"],
                subject="Other workspace ticket",
            )
            db.session.commit()

            # Client user is in workspace1 (seed_data workspace)
            user = _make_client_user(db.session, seed_data["workspace_id"])
            _make_subscription(db.session, seed_data["workspace_id"], "active")
            db.session.commit()
            user_email = user.email
            other_ticket_id = other_ticket.id

        _login(client, user_email, "clientpass")
        resp = client.get(f"/test-pizza/tickets/{other_ticket_id}", follow_redirects=True)
        assert resp.status_code == 200
        assert b"Ticket not found" in resp.data

    def test_ticket_reply(self, app, client, seed_data):
        with app.app_context():
            user = _make_client_user(db.session, seed_data["workspace_id"])
            _make_subscription(db.session, seed_data["workspace_id"], "active")
            ticket = _make_ticket(
                db.session, seed_data["workspace_id"],
                seed_data["site_id"], user.id,
            )
            db.session.commit()
            user_email = user.email
            ticket_id = ticket.id

        _login(client, user_email, "clientpass")
        resp = client.post(f"/test-pizza/tickets/{ticket_id}/reply", data={
            "message": "Thanks for the update!",
        }, follow_redirects=False)
        assert resp.status_code == 302

        # Verify message was added
        with app.app_context():
            messages = TicketMessage.query.filter_by(ticket_id=ticket_id).all()
            assert len(messages) == 1
            assert messages[0].message == "Thanks for the update!"
            assert messages[0].is_internal is False

    def test_ticket_reply_empty_message(self, app, client, seed_data):
        with app.app_context():
            user = _make_client_user(db.session, seed_data["workspace_id"])
            _make_subscription(db.session, seed_data["workspace_id"], "active")
            ticket = _make_ticket(
                db.session, seed_data["workspace_id"],
                seed_data["site_id"], user.id,
            )
            db.session.commit()
            user_email = user.email
            ticket_id = ticket.id

        _login(client, user_email, "clientpass")
        resp = client.post(f"/test-pizza/tickets/{ticket_id}/reply", data={
            "message": "",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"empty" in resp.data

    def test_ticket_reply_blocked_user(self, app, client, seed_data):
        """Blocked users cannot reply to tickets."""
        with app.app_context():
            user = _make_client_user(db.session, seed_data["workspace_id"])
            _make_subscription(db.session, seed_data["workspace_id"], "canceled")
            ticket = _make_ticket(
                db.session, seed_data["workspace_id"],
                seed_data["site_id"], user.id,
            )
            db.session.commit()
            user_email = user.email
            ticket_id = ticket.id

        _login(client, user_email, "clientpass")
        resp = client.post(f"/test-pizza/tickets/{ticket_id}/reply", data={
            "message": "Can you help?",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"active subscription" in resp.data

    def test_ticket_reply_auto_transitions_waiting(self, app, client, seed_data):
        """Client reply on waiting_on_client ticket auto-transitions to in_progress."""
        with app.app_context():
            user = _make_client_user(db.session, seed_data["workspace_id"])
            _make_subscription(db.session, seed_data["workspace_id"], "active")
            ticket = _make_ticket(
                db.session, seed_data["workspace_id"],
                seed_data["site_id"], user.id,
                status="waiting_on_client",
            )
            db.session.commit()
            user_email = user.email
            ticket_id = ticket.id

        _login(client, user_email, "clientpass")
        resp = client.post(f"/test-pizza/tickets/{ticket_id}/reply", data={
            "message": "Here's the info you asked for",
        }, follow_redirects=False)
        assert resp.status_code == 302

        with app.app_context():
            updated_ticket = db.session.get(Ticket, ticket_id)
            assert updated_ticket.status == "in_progress"
