"""Pitch template model.

Stores reusable pitch message templates that can be populated with
prospect-specific data (business name, demo URL, etc.) for quick
outreach via text, Facebook, or any non-email channel.

Template variables use {{variable}} syntax:
  {{business_name}}  — prospect's business name
  {{demo_url}}       — Cloudflare Pages demo link
  {{contact_name}}   — full contact name
  {{first_name}}     — first name only
  {{my_phone}}       — your phone number
  {{portal_url}}     — portal base URL
"""

import uuid

from app.extensions import db


class PitchTemplate(db.Model):
    __tablename__ = "pitch_templates"

    CATEGORIES = ["initial", "followup"]

    id = db.Column(
        db.String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name = db.Column(db.String(255), nullable=False)
    body = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(50), nullable=False, default="initial")
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(
        db.DateTime(timezone=True), server_default=db.func.now()
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        server_default=db.func.now(),
        onupdate=db.func.now(),
    )

    def render(self, prospect, portal_url="https://portal.belvieudigital.com", my_phone="(713) 725-4459"):
        """Replace template variables with prospect-specific values."""
        text = self.body
        replacements = {
            "{{business_name}}": prospect.business_name or "",
            "{{demo_url}}": prospect.demo_url or "",
            "{{contact_name}}": prospect.contact_name or "",
            "{{first_name}}": (prospect.contact_name or "").split(" ")[0] if prospect.contact_name else "",
            "{{my_phone}}": my_phone,
            "{{portal_url}}": portal_url,
        }
        for placeholder, value in replacements.items():
            text = text.replace(placeholder, value)
        return text

    def __repr__(self):
        return f"<PitchTemplate {self.name} ({'active' if self.is_active else 'inactive'})>"
