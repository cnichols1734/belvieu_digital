"""Webhooks blueprint — /stripe/webhooks

Receives Stripe webhook events. CSRF-exempt.
Raw body is required for signature verification.
"""

import logging

from flask import Blueprint, request, jsonify

from app.services.stripe_service import verify_webhook_signature, handle_webhook_event

logger = logging.getLogger(__name__)

webhooks_bp = Blueprint("webhooks", __name__, url_prefix="/stripe")


@webhooks_bp.route("/webhooks", methods=["POST"])
def stripe_webhook():
    """Receive and process Stripe webhook events.

    1. Get raw body (required for signature verification)
    2. Verify signature with STRIPE_WEBHOOK_SECRET
    3. Pass to handle_webhook_event (idempotent via stripe_events table)
    4. Return 200 to acknowledge receipt

    CSRF is exempted for this blueprint in create_app().
    """
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get("Stripe-Signature")

    if not sig_header:
        logger.warning("Webhook received without Stripe-Signature header")
        return jsonify({"error": "Missing signature"}), 400

    # --- Verify signature ---
    try:
        event = verify_webhook_signature(payload, sig_header)
    except Exception as e:
        logger.warning(f"Webhook signature verification failed: {e}")
        return jsonify({"error": "Invalid signature"}), 400

    # --- Process event (idempotent) ---
    success, message = handle_webhook_event(event)

    if success:
        return jsonify({"status": message}), 200
    else:
        logger.error(f"Webhook processing failed: {message}")
        return jsonify({"error": message}), 500
