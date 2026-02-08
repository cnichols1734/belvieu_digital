"""Tests for the auth blueprint — registration, login, logout.

Covers:
- Valid invite registration (email-locked and open)
- Expired invite rejection
- Used invite rejection
- Email-locked invite mismatch
- Duplicate email rejection
- Login with valid credentials
- Login with invalid credentials
- Login with deactivated account
- Logout
- Open redirect protection
- No-token redirect to login
- Registration creates workspace membership
- Registration creates audit event
"""

from app.models.user import User
from app.models.workspace import WorkspaceMember
from app.models.invite import WorkspaceInvite
from app.models.audit import AuditEvent


class TestRegistration:
    """Tests for the /auth/register route."""

    def test_register_page_loads_with_valid_token(self, client, seed_data):
        """GET /auth/register?token=<valid> should show registration form."""
        resp = client.get(f"/auth/register?token={seed_data['open_token']}")
        assert resp.status_code == 200
        assert b"Create your account" in resp.data

    def test_register_no_token_redirects_to_login(self, client, seed_data):
        """GET /auth/register with no token should redirect to login."""
        resp = client.get("/auth/register", follow_redirects=False)
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]

    def test_register_invalid_token_shows_error(self, client, seed_data):
        """GET /auth/register?token=bogus should show error state."""
        resp = client.get("/auth/register?token=totally-bogus-token")
        assert resp.status_code == 200
        assert b"Invalid invite link" in resp.data

    def test_register_expired_token_shows_error(self, client, seed_data):
        """GET /auth/register?token=<expired> should show error."""
        resp = client.get(f"/auth/register?token={seed_data['expired_token']}")
        assert resp.status_code == 200
        assert b"expired" in resp.data.lower()

    def test_register_used_token_shows_error(self, client, seed_data):
        """GET /auth/register?token=<used> should show error."""
        resp = client.get(f"/auth/register?token={seed_data['used_token']}")
        assert resp.status_code == 200
        assert b"already been used" in resp.data.lower()

    def test_register_success_open_invite(self, client, seed_data, app):
        """POST valid registration with an open invite (no email lock)."""
        resp = client.post(
            f"/auth/register?token={seed_data['open_token']}",
            data={
                "token": seed_data["open_token"],
                "email": "newuser@example.com",
                "password": "securepass123",
                "full_name": "New User",
            },
            follow_redirects=False,
        )
        # Should redirect to /<site_slug>/dashboard
        assert resp.status_code == 302
        assert "/test-pizza/dashboard" in resp.headers["Location"]

        # Verify user was created
        with app.app_context():
            user = User.query.filter_by(email="newuser@example.com").first()
            assert user is not None
            assert user.full_name == "New User"
            assert user.is_admin is False

            # Verify workspace membership
            membership = WorkspaceMember.query.filter_by(
                user_id=user.id,
                workspace_id=seed_data["workspace_id"],
            ).first()
            assert membership is not None
            # Workspace already has an owner (admin), so new user gets "member"
            assert membership.role == "member"

            # Verify invite consumed
            invite = WorkspaceInvite.query.filter_by(
                token=seed_data["open_token"]
            ).first()
            assert invite.used_at is not None

            # Verify audit event
            audit = AuditEvent.query.filter_by(
                action="user.registered",
                actor_user_id=user.id,
            ).first()
            assert audit is not None
            assert audit.workspace_id == seed_data["workspace_id"]

    def test_register_success_email_locked_invite(self, client, seed_data, app):
        """POST registration with email-locked invite using matching email."""
        resp = client.post(
            f"/auth/register?token={seed_data['invite_token']}",
            data={
                "token": seed_data["invite_token"],
                "email": "joe@testpizza.com",
                "password": "securepass123",
                "full_name": "Joe Test",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/test-pizza/dashboard" in resp.headers["Location"]

        with app.app_context():
            user = User.query.filter_by(email="joe@testpizza.com").first()
            assert user is not None

    def test_register_email_locked_mismatch(self, client, seed_data):
        """POST registration with wrong email on locked invite should fail."""
        resp = client.post(
            f"/auth/register?token={seed_data['invite_token']}",
            data={
                "token": seed_data["invite_token"],
                "email": "wrong@example.com",
                "password": "securepass123",
                "full_name": "Wrong Person",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"reserved for a different email" in resp.data.lower()

        # Invite should NOT be consumed
        invite = WorkspaceInvite.query.filter_by(
            token=seed_data["invite_token"]
        ).first()
        assert invite.used_at is None

    def test_register_duplicate_email(self, client, seed_data):
        """POST registration with existing email should fail."""
        resp = client.post(
            f"/auth/register?token={seed_data['open_token']}",
            data={
                "token": seed_data["open_token"],
                "email": "admin@waas.local",  # admin already exists
                "password": "securepass123",
                "full_name": "Duplicate",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"already exists" in resp.data.lower()

    def test_register_short_password(self, client, seed_data):
        """POST registration with password < 8 chars should fail."""
        resp = client.post(
            f"/auth/register?token={seed_data['open_token']}",
            data={
                "token": seed_data["open_token"],
                "email": "shortpw@example.com",
                "password": "short",
                "full_name": "Short Pass",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"at least 8 characters" in resp.data.lower()

    def test_register_missing_fields(self, client, seed_data):
        """POST registration with empty fields should fail."""
        resp = client.post(
            f"/auth/register?token={seed_data['open_token']}",
            data={
                "token": seed_data["open_token"],
                "email": "",
                "password": "",
                "full_name": "",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"required" in resp.data.lower()

    def test_register_expired_token_post(self, client, seed_data):
        """POST to expired token should fail."""
        resp = client.post(
            f"/auth/register?token={seed_data['expired_token']}",
            data={
                "token": seed_data["expired_token"],
                "email": "expired@example.com",
                "password": "securepass123",
                "full_name": "Expired Token",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"expired" in resp.data.lower()

    def test_register_used_token_post(self, client, seed_data):
        """POST to used token should fail."""
        resp = client.post(
            f"/auth/register?token={seed_data['used_token']}",
            data={
                "token": seed_data["used_token"],
                "email": "usedtoken@example.com",
                "password": "securepass123",
                "full_name": "Used Token",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"already been used" in resp.data.lower()


class TestLogin:
    """Tests for the /auth/login route."""

    def test_login_page_loads(self, client, seed_data):
        """GET /auth/login should show login form."""
        resp = client.get("/auth/login")
        assert resp.status_code == 200
        assert b"Log In" in resp.data

    def test_login_valid_credentials(self, client, seed_data):
        """POST with valid credentials should redirect."""
        resp = client.post(
            "/auth/login",
            data={
                "email": "admin@waas.local",
                "password": "admin123",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302

    def test_login_with_next_param(self, client, seed_data):
        """POST with valid credentials + next param should redirect to next."""
        resp = client.post(
            "/auth/login?next=/test-pizza/dashboard",
            data={
                "email": "admin@waas.local",
                "password": "admin123",
                "next": "/test-pizza/dashboard",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/test-pizza/dashboard" in resp.headers["Location"]

    def test_login_invalid_password(self, client, seed_data):
        """POST with wrong password should show error."""
        resp = client.post(
            "/auth/login",
            data={
                "email": "admin@waas.local",
                "password": "wrongpassword",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"Invalid email or password" in resp.data

    def test_login_nonexistent_email(self, client, seed_data):
        """POST with unknown email should show error."""
        resp = client.post(
            "/auth/login",
            data={
                "email": "nobody@example.com",
                "password": "anything",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"Invalid email or password" in resp.data

    def test_login_deactivated_account(self, client, seed_data, app):
        """POST with deactivated account should show error."""
        # Deactivate the admin account
        with app.app_context():
            admin = User.query.filter_by(email="admin@waas.local").first()
            admin.is_active = False
            from app.extensions import db
            db.session.commit()

        resp = client.post(
            "/auth/login",
            data={
                "email": "admin@waas.local",
                "password": "admin123",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"deactivated" in resp.data.lower()

    def test_login_missing_fields(self, client, seed_data):
        """POST with empty fields should show error."""
        resp = client.post(
            "/auth/login",
            data={"email": "", "password": ""},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"required" in resp.data.lower()

    def test_login_open_redirect_prevention(self, client, seed_data):
        """POST with external URL in next param should redirect to /."""
        resp = client.post(
            "/auth/login",
            data={
                "email": "admin@waas.local",
                "password": "admin123",
                "next": "https://evil.com/steal",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        # Should redirect to / not to evil.com
        location = resp.headers["Location"]
        assert "evil.com" not in location


class TestLogout:
    """Tests for the /auth/logout route."""

    def test_logout(self, client, seed_data):
        """GET /auth/logout should clear session and redirect to login."""
        # Log in first
        client.post(
            "/auth/login",
            data={"email": "admin@waas.local", "password": "admin123"},
        )

        resp = client.get("/auth/logout", follow_redirects=False)
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]

    def test_logout_when_not_logged_in(self, client, seed_data):
        """GET /auth/logout when not logged in should still redirect."""
        resp = client.get("/auth/logout", follow_redirects=False)
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]


class TestAuthenticatedRedirects:
    """Tests for behavior when user is already authenticated."""

    def test_login_page_redirects_when_authenticated(self, client, seed_data):
        """Authenticated user visiting /auth/login should be redirected."""
        # Log in
        client.post(
            "/auth/login",
            data={"email": "admin@waas.local", "password": "admin123"},
        )

        resp = client.get("/auth/login", follow_redirects=False)
        assert resp.status_code == 302

    def test_register_page_redirects_when_authenticated(self, client, seed_data):
        """Authenticated user visiting /auth/register should be redirected."""
        # Log in
        client.post(
            "/auth/login",
            data={"email": "admin@waas.local", "password": "admin123"},
        )

        resp = client.get(
            f"/auth/register?token={seed_data['open_token']}",
            follow_redirects=False,
        )
        assert resp.status_code == 302
