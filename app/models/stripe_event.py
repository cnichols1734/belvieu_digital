"""Stripe event model (idempotency table).

Every webhook event is recorded by its Stripe event ID. Before processing
any event, the handler checks this table. If the event_id already exists,
it returns 200 immediately — preventing double-writes from Stripe retries.
"""

import uuid

from app.extensions import db


class StripeEvent(db.Model):
    __tablename__ = "stripe_events"

    id = db.Column(
        db.String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    stripe_event_id = db.Column(
        db.String(255), unique=True, nullable=False
    )  # e.g. "evt_1Abc..."
    event_type = db.Column(
        db.String(255), nullable=False
    )  # e.g. "checkout.session.completed"
    processed_at = db.Column(
        db.DateTime(timezone=True), server_default=db.func.now()
    )

    def __repr__(self):
        return f"<StripeEvent {self.stripe_event_id} ({self.event_type})>"
