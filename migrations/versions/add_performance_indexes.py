"""Add performance indexes for frequently queried columns.

Revision ID: add_performance_indexes
Revises: cd77260a1e5a
Create Date: 2026-02-17

"""

from alembic import op
import sqlalchemy as sa


revision = "add_performance_indexes"
down_revision = "1b95973f361d"
branch_labels = None
depends_on = None


def upgrade():
    # Prospects - frequently filtered by status
    op.create_index("ix_prospects_status", "prospects", ["status"])
    op.create_index("ix_prospects_workspace_id", "prospects", ["workspace_id"])
    op.create_index("ix_prospects_updated_at", "prospects", ["updated_at"])

    # Billing subscriptions - heavily queried by status for dashboard
    op.create_index(
        "ix_billing_subscriptions_status", "billing_subscriptions", ["status"]
    )
    op.create_index(
        "ix_billing_subscriptions_workspace_id",
        "billing_subscriptions",
        ["workspace_id"],
    )
    op.create_index(
        "ix_billing_subscriptions_cancel_at_period_end",
        "billing_subscriptions",
        ["cancel_at_period_end"],
    )

    # Billing customers - queried by workspace
    op.create_index(
        "ix_billing_customers_workspace_id", "billing_customers", ["workspace_id"]
    )

    # Tickets - core performance issues
    op.create_index("ix_tickets_workspace_id", "tickets", ["workspace_id"])
    op.create_index("ix_tickets_status", "tickets", ["status"])
    op.create_index(
        "ix_tickets_assigned_to_user_id", "tickets", ["assigned_to_user_id"]
    )
    op.create_index("ix_tickets_last_activity_at", "tickets", ["last_activity_at"])
    op.create_index("ix_tickets_category", "tickets", ["category"])
    op.create_index("ix_tickets_site_id", "tickets", ["site_id"])

    # Composite index for common ticket queries (workspace + status + last_activity)
    op.create_index(
        "ix_tickets_workspace_status_activity",
        "tickets",
        ["workspace_id", "status", "last_activity_at"],
    )

    # Ticket messages - queried by ticket_id
    op.create_index("ix_ticket_messages_ticket_id", "ticket_messages", ["ticket_id"])
    op.create_index("ix_ticket_messages_created_at", "ticket_messages", ["created_at"])

    # Audit events - queried by workspace and action
    op.create_index("ix_audit_events_workspace_id", "audit_events", ["workspace_id"])
    op.create_index("ix_audit_events_actor_user_id", "audit_events", ["actor_user_id"])
    op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"])
    op.create_index("ix_audit_events_action", "audit_events", ["action"])

    # Workspace members - queried by both user and workspace
    op.create_index("ix_workspace_members_user_id", "workspace_members", ["user_id"])
    op.create_index(
        "ix_workspace_members_workspace_id", "workspace_members", ["workspace_id"]
    )

    # Sites - queried by workspace
    op.create_index("ix_sites_workspace_id", "sites", ["workspace_id"])

    # Workspace settings - queried by workspace
    op.create_index(
        "ix_workspace_settings_workspace_id", "workspace_settings", ["workspace_id"]
    )

    # Workspace invites - queried by workspace and used_at
    op.create_index(
        "ix_workspace_invites_workspace_id", "workspace_invites", ["workspace_id"]
    )
    op.create_index("ix_workspace_invites_used_at", "workspace_invites", ["used_at"])
    op.create_index(
        "ix_workspace_invites_expires_at", "workspace_invites", ["expires_at"]
    )

    # Stripe events - queried by processed_at
    op.create_index("ix_stripe_events_processed_at", "stripe_events", ["processed_at"])


def downgrade():
    op.drop_index("ix_stripe_events_processed_at", table_name="stripe_events")
    op.drop_index("ix_workspace_invites_expires_at", table_name="workspace_invites")
    op.drop_index("ix_workspace_invites_used_at", table_name="workspace_invites")
    op.drop_index("ix_workspace_invites_workspace_id", table_name="workspace_invites")
    op.drop_index("ix_workspace_settings_workspace_id", table_name="workspace_settings")
    op.drop_index("ix_sites_workspace_id", table_name="sites")
    op.drop_index("ix_workspace_members_workspace_id", table_name="workspace_members")
    op.drop_index("ix_workspace_members_user_id", table_name="workspace_members")
    op.drop_index("ix_audit_events_action", table_name="audit_events")
    op.drop_index("ix_audit_events_created_at", table_name="audit_events")
    op.drop_index("ix_audit_events_actor_user_id", table_name="audit_events")
    op.drop_index("ix_audit_events_workspace_id", table_name="audit_events")
    op.drop_index("ix_ticket_messages_created_at", table_name="ticket_messages")
    op.drop_index("ix_ticket_messages_ticket_id", table_name="ticket_messages")
    op.drop_index("ix_tickets_workspace_status_activity", table_name="tickets")
    op.drop_index("ix_tickets_site_id", table_name="tickets")
    op.drop_index("ix_tickets_category", table_name="tickets")
    op.drop_index("ix_tickets_last_activity_at", table_name="tickets")
    op.drop_index("ix_tickets_assigned_to_user_id", table_name="tickets")
    op.drop_index("ix_tickets_status", table_name="tickets")
    op.drop_index("ix_tickets_workspace_id", table_name="tickets")
    op.drop_index("ix_billing_customers_workspace_id", table_name="billing_customers")
    op.drop_index(
        "ix_billing_subscriptions_cancel_at_period_end",
        table_name="billing_subscriptions",
    )
    op.drop_index(
        "ix_billing_subscriptions_workspace_id", table_name="billing_subscriptions"
    )
    op.drop_index("ix_billing_subscriptions_status", table_name="billing_subscriptions")
    op.drop_index("ix_prospects_updated_at", table_name="prospects")
    op.drop_index("ix_prospects_workspace_id", table_name="prospects")
    op.drop_index("ix_prospects_status", table_name="prospects")
