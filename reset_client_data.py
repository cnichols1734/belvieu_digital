#!/usr/bin/env python3
"""Reset all client data from the local SQLite DB.

Keeps the admin user intact. Removes:
  - All non-admin users
  - All workspace memberships (non-admin)
  - All workspaces, sites, workspace settings
  - All prospects and prospect activities
  - All invites
  - All billing customers and subscriptions
  - All tickets and ticket messages
  - All audit events
  - All stripe events

Usage:
    python3 reset_client_data.py
    python3 reset_client_data.py --yes   (skip confirmation prompt)
"""

import sys
import os

# Ensure we can import the app
sys.path.insert(0, os.path.dirname(__file__))

# Load .env
from dotenv import load_dotenv
load_dotenv()


def reset():
    from app import create_app
    from app.extensions import db
    from app.models.user import User
    from app.models.workspace import Workspace, WorkspaceMember, WorkspaceSettings
    from app.models.site import Site
    from app.models.prospect import Prospect
    from app.models.prospect_activity import ProspectActivity
    from app.models.invite import WorkspaceInvite
    from app.models.billing import BillingCustomer, BillingSubscription
    from app.models.ticket import Ticket, TicketMessage
    from app.models.audit import AuditEvent
    from app.models.stripe_event import StripeEvent

    app = create_app("development")

    with app.app_context():
        # Show what we're keeping
        admins = User.query.filter_by(is_admin=True).all()
        admin_ids = [a.id for a in admins]

        print("\n  Admin users (will be KEPT):")
        for a in admins:
            print(f"    - {a.email} ({a.full_name or 'no name'})")

        non_admin_count = User.query.filter_by(is_admin=False).count()
        workspace_count = Workspace.query.count()
        prospect_count = Prospect.query.count()
        ticket_count = Ticket.query.count()

        print(f"\n  Data to be DELETED:")
        print(f"    - {non_admin_count} client user(s)")
        print(f"    - {workspace_count} workspace(s)")
        print(f"    - {prospect_count} prospect(s)")
        print(f"    - {ticket_count} ticket(s)")
        print(f"    - All invites, billing records, activities, audit logs, stripe events")
        print()

        if "--yes" not in sys.argv:
            confirm = input("  Proceed? (type 'yes' to confirm): ")
            if confirm.strip().lower() != "yes":
                print("  Aborted.")
                return

        # Delete in dependency order (children first)
        print("\n  Deleting...")

        n = TicketMessage.query.delete()
        print(f"    ticket_messages: {n}")

        n = Ticket.query.delete()
        print(f"    tickets: {n}")

        n = ProspectActivity.query.delete()
        print(f"    prospect_activities: {n}")

        n = WorkspaceInvite.query.delete()
        print(f"    workspace_invites: {n}")

        n = BillingSubscription.query.delete()
        print(f"    billing_subscriptions: {n}")

        n = BillingCustomer.query.delete()
        print(f"    billing_customers: {n}")

        n = WorkspaceSettings.query.delete()
        print(f"    workspace_settings: {n}")

        n = Site.query.delete()
        print(f"    sites: {n}")

        # Remove non-admin workspace memberships
        n = WorkspaceMember.query.delete()
        print(f"    workspace_members: {n}")

        # Clear prospect -> workspace FK before deleting workspaces
        Prospect.query.update({Prospect.workspace_id: None})
        n = Workspace.query.delete()
        print(f"    workspaces: {n}")

        n = Prospect.query.delete()
        print(f"    prospects: {n}")

        # Delete non-admin users
        n = User.query.filter(User.id.notin_(admin_ids)).delete()
        print(f"    users (non-admin): {n}")

        n = AuditEvent.query.delete()
        print(f"    audit_events: {n}")

        n = StripeEvent.query.delete()
        print(f"    stripe_events: {n}")

        db.session.commit()
        print("\n  Done! Client data cleared. Admin user(s) preserved.\n")


if __name__ == "__main__":
    reset()
