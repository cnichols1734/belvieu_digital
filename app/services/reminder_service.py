"""Reminder service — automated follow-up emails for pitched prospects.

Sends D3, D10, and D30 reminder emails to prospects who:
  - Have status "pitched" (not converted or declined)
  - Have a contact_email on file
  - Have already received the initial outreach email
  - Haven't already received the reminder for that tier

Designed to be called from a Flask CLI command (e.g. `flask send-reminders`)
on a daily cron schedule via Railway.
"""

import logging
from datetime import datetime, timezone

import click
from flask import current_app

from app.extensions import db
from app.models.prospect import Prospect
from app.models.prospect_activity import ProspectActivity
from app.models.invite import WorkspaceInvite
from app.services.email_service import send_email_sync

logger = logging.getLogger(__name__)

REMINDER_TIERS = [
    ("d3", 3),
    ("d10", 10),
    ("d30", 30),
]

REMINDER_SUBJECTS = {
    "d3": "Just making sure you saw this — {business_name}",
    "d10": "Your website for {business_name} is still ready",
    "d30": "Last reminder — your site link expires soon",
}


def _get_first_outreach_activity(prospect_id):
    """Return the first email-type ProspectActivity for a prospect, or None."""
    return (
        ProspectActivity.query
        .filter_by(prospect_id=prospect_id, activity_type="email")
        .filter(~ProspectActivity.note.contains("Reminder "))
        .order_by(ProspectActivity.created_at.asc())
        .first()
    )


def _has_reminder_been_sent(prospect_id, tier_label):
    """Check if a reminder for the given tier has already been sent."""
    marker = f"Reminder {tier_label} sent"
    return (
        ProspectActivity.query
        .filter_by(prospect_id=prospect_id, activity_type="email")
        .filter(ProspectActivity.note.contains(marker))
        .first()
    ) is not None


def _get_invite_link(prospect):
    """Find a valid (unused, unexpired) invite link for the prospect's workspace."""
    if not prospect.workspace_id:
        return None

    invite = (
        WorkspaceInvite.query
        .filter_by(workspace_id=prospect.workspace_id)
        .filter(WorkspaceInvite.used_at.is_(None))
        .order_by(WorkspaceInvite.created_at.desc())
        .first()
    )

    if invite and invite.is_valid:
        base_url = current_app.config["APP_BASE_URL"]
        return f"{base_url}/auth/register?token={invite.token}"

    return None


def _log_reminder_activity(prospect_id, tier_label, email):
    """Log a ProspectActivity for the sent reminder."""
    activity = ProspectActivity(
        prospect_id=prospect_id,
        activity_type="email",
        note=f"Reminder {tier_label} sent to {email}",
        actor_user_id=None,
    )
    db.session.add(activity)


def process_reminders(dry_run=False):
    """Find eligible prospects and send reminder emails.

    Args:
        dry_run: If True, log what would be sent but don't actually send.

    Returns:
        int: Number of reminders sent (or would-be-sent in dry-run mode).
    """
    now = datetime.now(timezone.utc)
    sent_count = 0

    if dry_run:
        click.echo("[DRY RUN] No emails will actually be sent.\n")

    prospects = (
        Prospect.query
        .filter(Prospect.status == "pitched")
        .filter(Prospect.contact_email.isnot(None))
        .filter(Prospect.contact_email != "")
        .all()
    )

    click.echo(f"Found {len(prospects)} pitched prospect(s) with an email address.")

    if not prospects:
        all_prospects = Prospect.query.count()
        pitched = Prospect.query.filter_by(status="pitched").count()
        click.echo(f"  Total prospects in DB: {all_prospects}")
        click.echo(f"  With status 'pitched': {pitched}")
        if pitched > 0:
            click.echo("  None of the pitched prospects have a contact_email set.")
        return 0

    click.echo("")

    for prospect in prospects:
        click.echo(f"── {prospect.business_name} ({prospect.contact_email}) ──")

        first_outreach = _get_first_outreach_activity(prospect.id)
        if not first_outreach:
            click.echo("   SKIP: No outreach email activity found for this prospect.")
            click.echo("         (An outreach email must be sent first via the admin panel.)\n")
            continue

        pitch_date = first_outreach.created_at
        if pitch_date.tzinfo is None:
            pitch_date = pitch_date.replace(tzinfo=timezone.utc)
        days_since_pitch = (now - pitch_date).days

        click.echo(f"   Outreach sent: {pitch_date.strftime('%Y-%m-%d')} ({days_since_pitch} days ago)")

        # Walk tiers highest-to-lowest to find the best one to send.
        # If a prospect is 10 days out with no reminders, send D10 — not D3.
        target_tier = None
        for tier_label, tier_days in reversed(REMINDER_TIERS):
            already_sent = _has_reminder_been_sent(prospect.id, tier_label)

            if already_sent:
                click.echo(f"   {tier_label.upper()} (>={tier_days}d): already sent")
                continue

            if days_since_pitch >= tier_days:
                target_tier = (tier_label, tier_days)
                break

        # Log the tiers we're skipping for clarity
        if target_tier:
            t_label, t_days = target_tier
            for tier_label, tier_days in REMINDER_TIERS:
                if tier_days < t_days and not _has_reminder_been_sent(prospect.id, tier_label):
                    click.echo(f"   {tier_label.upper()} (>={tier_days}d): skipped (superseded by {t_label.upper()})")

        # Also show tiers that are not yet eligible
        for tier_label, tier_days in REMINDER_TIERS:
            if days_since_pitch < tier_days and not _has_reminder_been_sent(prospect.id, tier_label):
                click.echo(f"   {tier_label.upper()} (>={tier_days}d): not yet eligible ({tier_days - days_since_pitch}d to go)")

        sent_this_prospect = False

        if not target_tier:
            click.echo("   No action needed for this prospect.")
        else:
            tier_label, tier_days = target_tier
            invite_link = _get_invite_link(prospect)
            subject = REMINDER_SUBJECTS[tier_label].format(
                business_name=prospect.business_name,
            )
            reply_to = current_app.config.get("MAIL_FROM_ADDRESS")

            if dry_run:
                click.echo(f"   {tier_label.upper()} (>={tier_days}d): WOULD SEND → {prospect.contact_email}")
                click.echo(f"      Subject: {subject}")
                sent_count += 1
                sent_this_prospect = True
            else:
                click.echo(f"   {tier_label.upper()} (>={tier_days}d): SENDING → {prospect.contact_email}")
                click.echo(f"      Subject: {subject}")

                try:
                    send_email_sync(
                        to=prospect.contact_email,
                        subject=subject,
                        template="emails/prospect_reminder.html",
                        context={
                            "business_name": prospect.business_name,
                            "contact_name": prospect.contact_name,
                            "demo_url": prospect.demo_url,
                            "invite_link": invite_link,
                            "reminder_tier": tier_label,
                        },
                        reply_to=reply_to,
                    )

                    _log_reminder_activity(prospect.id, tier_label, prospect.contact_email)
                    db.session.commit()
                    sent_count += 1
                    sent_this_prospect = True
                    click.echo("      ✓ Sent and logged.")

                except Exception as e:
                    click.echo(f"      ✗ FAILED: {e}")
                    db.session.rollback()

        click.echo("")

    click.echo(f"{'[DRY RUN] ' if dry_run else ''}Done: {sent_count} reminder(s) {'would be ' if dry_run else ''}sent.")
    return sent_count
