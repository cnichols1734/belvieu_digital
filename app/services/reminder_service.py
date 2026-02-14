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

from flask import current_app

from app.extensions import db
from app.models.prospect import Prospect
from app.models.prospect_activity import ProspectActivity
from app.models.invite import WorkspaceInvite
from app.services.email_service import send_email_sync

logger = logging.getLogger(__name__)

# Reminder tiers: (label, days_after_pitch)
REMINDER_TIERS = [
    ("d3", 3),
    ("d10", 10),
    ("d30", 30),
]

# Subject lines per tier
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
        actor_user_id=None,  # system-generated
    )
    db.session.add(activity)


def process_reminders():
    """Find eligible prospects and send reminder emails.

    Returns:
        int: Number of reminders sent.
    """
    now = datetime.now(timezone.utc)
    sent_count = 0

    # All prospects that were pitched, have an email, and haven't converted/declined
    prospects = (
        Prospect.query
        .filter(Prospect.status == "pitched")
        .filter(Prospect.contact_email.isnot(None))
        .filter(Prospect.contact_email != "")
        .all()
    )

    logger.info(f"Reminder check: found {len(prospects)} pitched prospect(s) with email.")

    for prospect in prospects:
        # Find when the first outreach email was sent
        first_outreach = _get_first_outreach_activity(prospect.id)
        if not first_outreach:
            logger.debug(f"  {prospect.business_name}: no outreach email found, skipping.")
            continue

        # Calculate days since first pitch email
        pitch_date = first_outreach.created_at
        if pitch_date.tzinfo is None:
            pitch_date = pitch_date.replace(tzinfo=timezone.utc)
        days_since_pitch = (now - pitch_date).days

        # Check each tier (in order) and send the first eligible one
        for tier_label, tier_days in REMINDER_TIERS:
            if days_since_pitch >= tier_days and not _has_reminder_been_sent(prospect.id, tier_label):
                # Build context for the template
                invite_link = _get_invite_link(prospect)
                subject = REMINDER_SUBJECTS[tier_label].format(
                    business_name=prospect.business_name,
                )
                reply_to = current_app.config.get("MAIL_FROM_ADDRESS")

                logger.info(
                    f"  Sending {tier_label} reminder to {prospect.contact_email} "
                    f"for {prospect.business_name} (pitched {days_since_pitch}d ago)."
                )

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

                except Exception as e:
                    logger.error(
                        f"  Failed to send {tier_label} reminder to "
                        f"{prospect.contact_email}: {e}"
                    )
                    db.session.rollback()

                # Only send one reminder per prospect per run
                break

    logger.info(f"Reminder run complete: {sent_count} reminder(s) sent.")
    return sent_count
