"""Shared test fixtures for the WaaS Portal test suite.

Provides:
- app: Flask app configured for testing (in-memory SQLite, CSRF off)
- client: Flask test client
- db_session: clean database per test (tables created/dropped)
- seed_data: pre-populated workspace, site, invite, admin user
"""

import secrets
from datetime import datetime, timedelta, timezone

import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from app.extensions import db as _db
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember, WorkspaceSettings
from app.models.prospect import Prospect
from app.models.site import Site
from app.models.invite import WorkspaceInvite


@pytest.fixture(scope="session")
def app():
    """Create the Flask application configured for testing."""
    app = create_app("testing")
    yield app


@pytest.fixture(autouse=True)
def db_session(app):
    """Create all tables before each test, drop after.

    Uses a nested transaction so each test gets a clean slate.
    """
    with app.app_context():
        _db.create_all()
        yield _db.session
        _db.session.rollback()
        _db.drop_all()


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()


@pytest.fixture
def seed_data(app, db_session):
    """Seed the database with an admin user, prospect, workspace, site, and invite.

    Returns a dict with all created objects for easy access in tests.
    """
    with app.app_context():
        # --- Admin user ---
        admin = User(
            email="admin@waas.local",
            password_hash=generate_password_hash("admin123"),
            full_name="Admin User",
            is_admin=True,
        )
        _db.session.add(admin)
        _db.session.flush()

        # --- Prospect ---
        prospect = Prospect(
            business_name="Test Pizza Shop",
            contact_name="Joe Test",
            contact_email="joe@testpizza.com",
            source="google_maps",
            status="converted",
        )
        _db.session.add(prospect)
        _db.session.flush()

        # --- Workspace ---
        workspace = Workspace(
            name="Test Pizza Shop",
            prospect_id=prospect.id,
        )
        _db.session.add(workspace)
        _db.session.flush()

        prospect.workspace_id = workspace.id

        # --- Workspace settings ---
        settings = WorkspaceSettings(workspace_id=workspace.id)
        _db.session.add(settings)

        # --- Admin as workspace member ---
        admin_membership = WorkspaceMember(
            user_id=admin.id,
            workspace_id=workspace.id,
            role="owner",
        )
        _db.session.add(admin_membership)

        # --- Site ---
        site = Site(
            workspace_id=workspace.id,
            site_slug="test-pizza",
            display_name="Test Pizza Shop",
            published_url="https://testpizza.example.dev",
            status="demo",
        )
        _db.session.add(site)
        _db.session.flush()

        # --- Invite (valid, email-locked) ---
        token = secrets.token_urlsafe(48)
        invite = WorkspaceInvite(
            workspace_id=workspace.id,
            site_id=site.id,
            email="joe@testpizza.com",
            token=token,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        _db.session.add(invite)

        # --- Open invite (no email lock) ---
        open_token = secrets.token_urlsafe(48)
        open_invite = WorkspaceInvite(
            workspace_id=workspace.id,
            site_id=site.id,
            email=None,
            token=open_token,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        _db.session.add(open_invite)

        # --- Expired invite ---
        expired_token = secrets.token_urlsafe(48)
        expired_invite = WorkspaceInvite(
            workspace_id=workspace.id,
            site_id=site.id,
            email=None,
            token=expired_token,
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        _db.session.add(expired_invite)

        # --- Used invite ---
        used_token = secrets.token_urlsafe(48)
        used_invite = WorkspaceInvite(
            workspace_id=workspace.id,
            site_id=site.id,
            email=None,
            token=used_token,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            used_at=datetime.now(timezone.utc),
        )
        _db.session.add(used_invite)

        _db.session.commit()

        # Store plain IDs so tests can use them even when objects
        # are detached from the session (cross-context access).
        return {
            "admin": admin,
            "admin_id": admin.id,
            "prospect": prospect,
            "workspace": workspace,
            "workspace_id": workspace.id,
            "settings": settings,
            "site": site,
            "site_id": site.id,
            "site_slug": site.site_slug,
            "invite": invite,  # email-locked to joe@testpizza.com
            "invite_token": token,
            "open_invite": open_invite,  # no email lock
            "open_token": open_token,
            "expired_invite": expired_invite,
            "expired_token": expired_token,
            "used_invite": used_invite,
            "used_token": used_token,
        }
