"""
Contact form blueprint.

Handles the landing page contact form submission — sends a notification
to the business and a confirmation email to the visitor.
"""

import logging
import re

from flask import Blueprint, jsonify, request, current_app
from app.extensions import limiter

contact_bp = Blueprint("contact", __name__, url_prefix="/contact")

logger = logging.getLogger(__name__)

# Simple email regex — not exhaustive, just sanity-check
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@contact_bp.route("/send", methods=["POST"])
@limiter.limit("5 per hour")
def send_contact():
    """
    Accept a JSON contact form submission.

    Expects: { name, email, phone (optional), message }
    Returns: { ok: true } or { ok: false, error: "..." }
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify(ok=False, error="Invalid request."), 400

    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    phone = (data.get("phone") or "").strip()
    message = (data.get("message") or "").strip()

    # --- Validation ---
    errors = []
    if not name:
        errors.append("Name is required.")
    if not email or not EMAIL_RE.match(email):
        errors.append("A valid email is required.")
    if not message:
        errors.append("Message is required.")
    if len(message) > 5000:
        errors.append("Message is too long.")

    if errors:
        return jsonify(ok=False, error=" ".join(errors)), 422

    # --- Send emails ---
    from app.services.email_service import send_email

    business_email = current_app.config.get("MAIL_CONTACT_TO", "info@belvieudigital.com")

    # 1. Notification to the business (reply-to = the visitor)
    send_email(
        to=business_email,
        subject=f"New inquiry from {name}",
        template="emails/contact_notification.html",
        context={"name": name, "email": email, "phone": phone, "message": message},
        reply_to=email,
    )

    # 2. Confirmation to the visitor
    send_email(
        to=email,
        subject="We received your message — Belvieu Digital",
        template="emails/contact_confirmation.html",
        context={"name": name, "message": message},
    )

    logger.info(f"Contact form submitted by {name} <{email}>")

    return jsonify(ok=True), 200
