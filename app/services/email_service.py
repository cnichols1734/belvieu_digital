"""
Modular email service for WaaS Portal.

Uses Google Workspace SMTP (smtp.gmail.com) to send transactional emails.
Designed to be reusable across the entire app — contact forms, notifications,
ticket updates, billing alerts, etc.

Usage:
    from app.services.email_service import send_email

    send_email(
        to="user@example.com",
        subject="Hello",
        template="emails/welcome.html",
        context={"name": "Jane"},
    )
"""

import logging
import smtplib
import threading
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flask import current_app, render_template

logger = logging.getLogger(__name__)


def _send_smtp(app, msg):
    """Send an email via SMTP in a background thread (non-blocking)."""
    with app.app_context():
        host = app.config.get("MAIL_SMTP_HOST", "smtp.gmail.com")
        port = app.config.get("MAIL_SMTP_PORT", 587)
        username = app.config.get("MAIL_USERNAME")
        password = app.config.get("MAIL_PASSWORD")

        if not username or not password:
            logger.warning("Email not sent — MAIL_USERNAME or MAIL_PASSWORD not configured.")
            return

        try:
            with smtplib.SMTP(host, port, timeout=30) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(username, password)
                server.send_message(msg)
            logger.info(f"Email sent to {msg['To']} — {msg['Subject']}")
        except Exception as e:
            logger.error(f"Failed to send email to {msg['To']}: {e}")


def send_email(to, subject, template, context=None, reply_to=None):
    """
    Send a templated HTML email.

    Args:
        to:        Recipient email address (str or list).
        subject:   Email subject line.
        template:  Path to Jinja2 HTML template (relative to templates/).
        context:   Dict of variables to pass to the template.
        reply_to:  Optional reply-to address.
    """
    app = current_app._get_current_object()
    context = context or {}

    from_name = app.config.get("MAIL_FROM_NAME", "Belvieu Digital")
    from_email = app.config.get("MAIL_FROM_ADDRESS", app.config.get("MAIL_USERNAME", ""))

    # Render the HTML template
    html_body = render_template(template, **context)

    # Build the message
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{from_email}>"
    msg["To"] = to if isinstance(to, str) else ", ".join(to)

    if reply_to:
        msg["Reply-To"] = reply_to

    msg.attach(MIMEText(html_body, "html"))

    # Send in background thread so the request doesn't block
    thread = threading.Thread(target=_send_smtp, args=(app, msg))
    thread.daemon = True
    thread.start()


def send_email_sync(to, subject, template, context=None, reply_to=None):
    """
    Same as send_email but blocks until sent. Use for critical emails
    where you need to confirm delivery before responding.
    """
    app = current_app._get_current_object()
    context = context or {}

    from_name = app.config.get("MAIL_FROM_NAME", "Belvieu Digital")
    from_email = app.config.get("MAIL_FROM_ADDRESS", app.config.get("MAIL_USERNAME", ""))

    html_body = render_template(template, **context)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{from_email}>"
    msg["To"] = to if isinstance(to, str) else ", ".join(to)

    if reply_to:
        msg["Reply-To"] = reply_to

    msg.attach(MIMEText(html_body, "html"))

    _send_smtp(app, msg)
