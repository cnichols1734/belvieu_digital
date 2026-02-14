"""Form relay blueprint — /api/forms/*

Public API endpoint that receives contact form submissions from client
websites and forwards them via email to configured recipients.

Works like Web3Forms: client embeds an HTML form with a hidden access_key
field. No JavaScript required — a plain <form> POST works.

Route Map:
  POST /api/forms/submit  — Accept form submission, relay via email
  OPTIONS /api/forms/submit — CORS preflight
"""

import logging
import re

from flask import Blueprint, jsonify, redirect as flask_redirect, request, make_response

from app.extensions import db, limiter
from app.models.contact_form import ContactFormConfig

form_relay_bp = Blueprint("form_relay", __name__, url_prefix="/api/forms")

logger = logging.getLogger(__name__)

# Simple email regex — not exhaustive, just sanity-check
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _cors_response(response):
    """Add CORS headers so cross-origin JS submissions work."""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


@form_relay_bp.route("/submit", methods=["OPTIONS"])
def submit_preflight():
    """Handle CORS preflight requests."""
    response = make_response("", 204)
    return _cors_response(response)


@form_relay_bp.route("/submit", methods=["POST"])
@limiter.limit("10 per hour")
def submit():
    """
    Accept a contact form submission and relay it via email.

    Accepts both JSON and standard HTML form POST (application/x-www-form-urlencoded).

    Required fields: access_key, name, email, message
    Optional fields: phone

    Returns: { ok: true } or { ok: false, error: "..." }
    """
    # --- Extract data from either JSON or form POST ---
    if request.is_json:
        data = request.get_json(silent=True) or {}
    else:
        data = request.form.to_dict()

    if not data:
        return _cors_response(jsonify(ok=False, error="Invalid request.")), 400

    access_key = (data.get("access_key") or "").strip()
    redirect_url = (data.get("redirect") or "").strip()
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    phone = (data.get("phone") or "").strip()
    message = (data.get("message") or "").strip()

    # --- Validate access key ---
    if not access_key:
        return _cors_response(
            jsonify(ok=False, error="Missing access key.")
        ), 403

    config = ContactFormConfig.query.filter_by(access_key=access_key).first()

    if config is None:
        return _cors_response(
            jsonify(ok=False, error="Invalid access key.")
        ), 403

    if not config.is_enabled:
        return _cors_response(
            jsonify(ok=False, error="This form is currently disabled.")
        ), 403

    # --- Validate form fields ---
    errors = []
    if not name:
        errors.append("Name is required.")
    if not email or not EMAIL_RE.match(email):
        errors.append("A valid email is required.")
    if not message:
        errors.append("Message is required.")
    if len(message) > 5000:
        errors.append("Message is too long.")
    if len(name) > 200:
        errors.append("Name is too long.")

    if errors:
        return _cors_response(
            jsonify(ok=False, error=" ".join(errors))
        ), 422

    # --- Resolve site display name for the email subject ---
    site = config.site
    site_name = site.display_name or site.site_slug if site else "Unknown Site"

    # --- Send email to all configured recipients ---
    from app.services.email_service import send_email

    recipients = config.get_recipient_list()
    if not recipients:
        logger.error(
            f"Contact form config {config.id} has no recipient emails configured."
        )
        return _cors_response(
            jsonify(ok=False, error="Form configuration error. Please try again later.")
        ), 500

    send_email(
        to=recipients,
        subject=f"New message from {name} via {site_name}",
        template="emails/form_relay_notification.html",
        context={
            "name": name,
            "email": email,
            "phone": phone,
            "message": message,
            "site_name": site_name,
        },
        reply_to=email,
    )

    logger.info(
        f"Form relay: message from {name} <{email}> forwarded to "
        f"{', '.join(recipients)} (site: {site_name})"
    )

    # If a redirect URL was provided, send the browser there instead of JSON
    if redirect_url and redirect_url.startswith("http"):
        return flask_redirect(redirect_url)

    return _cors_response(jsonify(ok=True)), 200
