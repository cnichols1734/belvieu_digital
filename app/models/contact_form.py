"""ContactFormConfig model.

Stores per-site configuration for the contact form relay service.
Each site can have one config with an access key (token) that gets
embedded in the client website's HTML form. When a visitor submits
the form, the relay endpoint looks up this config to determine
where to forward the email.
"""

import secrets
import uuid

from app.extensions import db


class ContactFormConfig(db.Model):
    __tablename__ = "contact_form_configs"

    id = db.Column(
        db.String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    site_id = db.Column(
        db.String(36),
        db.ForeignKey("sites.id"),
        unique=True,
        nullable=False,
    )
    access_key = db.Column(
        db.String(100), unique=True, nullable=False
    )
    recipient_emails = db.Column(
        db.Text, nullable=False
    )  # comma-separated emails, e.g. "owner@biz.com,manager@biz.com"
    is_enabled = db.Column(db.Boolean, default=True, nullable=False)

    created_at = db.Column(
        db.DateTime(timezone=True), server_default=db.func.now()
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        server_default=db.func.now(),
        onupdate=db.func.now(),
    )

    # --- Relationships ---
    site = db.relationship("Site", backref=db.backref("contact_form_config", uselist=False))

    @staticmethod
    def generate_access_key():
        """Generate a secure access key (~64-char base64 string)."""
        return secrets.token_urlsafe(48)

    def get_recipient_list(self):
        """Return recipient_emails as a cleaned list."""
        if not self.recipient_emails:
            return []
        return [
            e.strip() for e in self.recipient_emails.split(",") if e.strip()
        ]

    def __repr__(self):
        return f"<ContactFormConfig site_id={self.site_id} enabled={self.is_enabled}>"
