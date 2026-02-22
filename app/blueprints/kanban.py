"""Kanban blueprint — /admin/kanban/*

Internal research pipeline board with drag-and-drop columns and cards.
All routes require admin access. API routes are CSRF-exempt (admin-only + auth).
API routes also accept Bearer token auth via KANBAN_API_KEY for bot access.

Route Map:
  GET  /admin/kanban                           — Board page
  GET  /admin/kanban/api/board                 — Full board JSON
  POST /admin/kanban/api/columns               — Create column
  PUT  /admin/kanban/api/columns/<id>          — Update column
  DELETE /admin/kanban/api/columns/<id>        — Delete column
  PUT  /admin/kanban/api/columns/reorder       — Reorder columns
  POST /admin/kanban/api/cards                 — Create card
  PUT  /admin/kanban/api/cards/<id>            — Update card
  DELETE /admin/kanban/api/cards/<id>          — Delete card
  PUT  /admin/kanban/api/cards/reorder         — Reorder cards
  POST /admin/kanban/api/cards/<id>/comments   — Add comment
  POST /admin/kanban/api/cards/<id>/create-prospect — Parse card → Prospect
"""

import json
import re
import uuid
from datetime import datetime, timezone
from functools import wraps

from flask import Blueprint, current_app, jsonify, render_template, request
from flask_login import current_user

from app.decorators import admin_required
from app.extensions import db
from app.models.audit import AuditEvent
from app.models.kanban import KanbanCard, KanbanColumn
from app.models.prospect import Prospect

kanban_bp = Blueprint("kanban", __name__, url_prefix="/admin/kanban")


def _kanban_api_auth(f):
    """Allow access via admin session OR a Bearer token matching KANBAN_API_KEY."""
    @wraps(f)
    def decorated(*args, **kwargs):
        # Check Bearer token first (for bot/external access)
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            expected = current_app.config.get("KANBAN_API_KEY") or ""
            if expected and token == expected:
                return f(*args, **kwargs)
            return jsonify({"error": "Invalid API key"}), 401

        # Fall back to admin session auth
        if not current_user.is_authenticated or not current_user.is_admin:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


# ─── Page Route ──────────────────────────────────────────────────

@kanban_bp.route("")
@admin_required
def board():
    return render_template("admin/kanban.html")


# ─── Board API ───────────────────────────────────────────────────

@kanban_bp.route("/api/board")
@_kanban_api_auth
def api_board():
    columns = KanbanColumn.query.order_by(KanbanColumn.position).all()
    result = []
    for col in columns:
        cards = (
            KanbanCard.query
            .filter_by(kanban_column_id=col.id)
            .order_by(KanbanCard.position)
            .all()
        )
        result.append({
            "id": col.id,
            "title": col.title,
            "position": col.position,
            "created_at": col.created_at.isoformat() if col.created_at else None,
            "cards": [_card_dict(c) for c in cards],
        })
    return jsonify(result)


# ─── Column API ──────────────────────────────────────────────────

@kanban_bp.route("/api/columns", methods=["POST"])
@_kanban_api_auth
def api_create_column():
    data = request.get_json(force=True)
    max_pos = db.session.query(db.func.max(KanbanColumn.position)).scalar() or -1
    col = KanbanColumn(
        title=data.get("title", "New Column"),
        position=max_pos + 1,
    )
    db.session.add(col)
    db.session.commit()
    return jsonify({"id": col.id, "title": col.title, "position": col.position}), 201


@kanban_bp.route("/api/columns/<col_id>", methods=["PUT"])
@_kanban_api_auth
def api_update_column(col_id):
    col = db.session.get(KanbanColumn, col_id)
    if not col:
        return jsonify({"error": "Column not found"}), 404
    data = request.get_json(force=True)
    if "title" in data:
        col.title = data["title"]
    if "position" in data:
        col.position = data["position"]
    db.session.commit()
    return jsonify({"id": col.id, "title": col.title, "position": col.position})


@kanban_bp.route("/api/columns/<col_id>", methods=["DELETE"])
@_kanban_api_auth
def api_delete_column(col_id):
    col = db.session.get(KanbanColumn, col_id)
    if col:
        db.session.delete(col)
        db.session.commit()
    return jsonify({"success": True})


@kanban_bp.route("/api/columns/reorder", methods=["PUT"])
@_kanban_api_auth
def api_reorder_columns():
    data = request.get_json(force=True)
    for i, cid in enumerate(data.get("column_ids", [])):
        col = db.session.get(KanbanColumn, cid)
        if col:
            col.position = i
    db.session.commit()
    return jsonify({"success": True})


# ─── Card API ────────────────────────────────────────────────────

@kanban_bp.route("/api/cards", methods=["POST"])
@_kanban_api_auth
def api_create_card():
    data = request.get_json(force=True)
    col_id = data["column_id"]
    max_pos = (
        db.session.query(db.func.max(KanbanCard.position))
        .filter_by(kanban_column_id=col_id)
        .scalar()
    )
    max_pos = max_pos if max_pos is not None else -1
    next_num = (db.session.query(db.func.max(KanbanCard.card_number)).scalar() or 0) + 1
    card = KanbanCard(
        kanban_column_id=col_id,
        card_number=next_num,
        title=data.get("title", "New Card"),
        description=data.get("description", ""),
        position=max_pos + 1,
        labels=json.dumps(data.get("labels", [])) if isinstance(data.get("labels"), list) else data.get("labels", "[]"),
    )
    db.session.add(card)
    db.session.commit()
    return jsonify(_card_dict(card)), 201


@kanban_bp.route("/api/cards/<card_id>", methods=["PUT"])
@_kanban_api_auth
def api_update_card(card_id):
    card = db.session.get(KanbanCard, card_id)
    if not card:
        return jsonify({"error": "Card not found"}), 404
    data = request.get_json(force=True)
    for key in ("title", "description", "kanban_column_id", "position"):
        if key in data:
            setattr(card, key, data[key])
    if "column_id" in data:
        card.kanban_column_id = data["column_id"]
    if "labels" in data:
        val = data["labels"]
        card.labels = json.dumps(val) if isinstance(val, list) else val
    card.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify(_card_dict(card))


@kanban_bp.route("/api/cards/<card_id>", methods=["DELETE"])
@_kanban_api_auth
def api_delete_card(card_id):
    card = db.session.get(KanbanCard, card_id)
    if card:
        db.session.delete(card)
        db.session.commit()
    return jsonify({"success": True})


@kanban_bp.route("/api/cards/reorder", methods=["PUT"])
@_kanban_api_auth
def api_reorder_cards():
    data = request.get_json(force=True)
    now = datetime.now(timezone.utc)
    for item in data.get("cards", []):
        card = db.session.get(KanbanCard, item["id"])
        if card:
            card.kanban_column_id = item["column_id"]
            card.position = item["position"]
            card.updated_at = now
    db.session.commit()
    return jsonify({"success": True})


# ─── Comments API ────────────────────────────────────────────────

@kanban_bp.route("/api/cards/<card_id>/comments", methods=["GET"])
@_kanban_api_auth
def api_get_comments(card_id):
    card = db.session.get(KanbanCard, card_id)
    if not card:
        return jsonify([])
    try:
        comments = json.loads(card.comments) if card.comments else []
    except (json.JSONDecodeError, TypeError):
        comments = []
    return jsonify(comments)


@kanban_bp.route("/api/cards/<card_id>/comments", methods=["POST"])
@_kanban_api_auth
def api_add_comment(card_id):
    card = db.session.get(KanbanCard, card_id)
    if not card:
        return jsonify({"error": "Card not found"}), 404
    data = request.get_json(force=True)
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"error": "Comment text required"}), 400

    try:
        comments = json.loads(card.comments) if card.comments else []
    except (json.JSONDecodeError, TypeError):
        comments = []

    comments.append({
        "author": data.get("author", "Anonymous"),
        "text": text,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    card.comments = json.dumps(comments)
    card.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({"success": True}), 201


# ─── Create Prospect from Card ───────────────────────────────────

@kanban_bp.route("/api/cards/<card_id>/create-prospect", methods=["POST"])
@_kanban_api_auth
def api_create_prospect(card_id):
    card = db.session.get(KanbanCard, card_id)
    if not card:
        return jsonify({"error": "Card not found"}), 404
    if card.prospect_id:
        return jsonify({"error": "Card already linked to a prospect", "prospect_id": card.prospect_id}), 409

    desc = card.description or ""
    parsed = _parse_card_markdown(desc, card.title)

    prospect = Prospect(
        business_name=parsed["business_name"],
        contact_name=parsed.get("contact_name"),
        contact_email=parsed.get("contact_email"),
        contact_phone=parsed.get("contact_phone"),
        source=parsed["source"],
        source_url=parsed.get("source_url"),
        notes=desc,
        demo_url=parsed.get("demo_url"),
        status="researching",
    )
    db.session.add(prospect)
    db.session.flush()

    card.prospect_id = prospect.id
    card.updated_at = datetime.now(timezone.utc)

    actor_id = current_user.id if current_user.is_authenticated else None
    db.session.add(AuditEvent(
        actor_user_id=actor_id,
        action="prospect.created",
        metadata_=json.dumps({
            "prospect_id": prospect.id,
            "business_name": prospect.business_name,
            "source": "kanban_card",
            "kanban_card_id": card.id,
        }),
    ))

    db.session.commit()
    return jsonify({
        "success": True,
        "prospect_id": prospect.id,
        "business_name": prospect.business_name,
        "source": prospect.source,
    }), 201


# ─── Helpers ─────────────────────────────────────────────────────

def _card_dict(card):
    """Serialize a KanbanCard to a JSON-safe dict."""
    try:
        comments = json.loads(card.comments) if card.comments else []
    except (json.JSONDecodeError, TypeError):
        comments = []
    return {
        "id": card.id,
        "card_number": card.card_number,
        "column_id": card.kanban_column_id,
        "title": card.title,
        "description": card.description or "",
        "position": card.position,
        "labels": card.labels or "[]",
        "comments": comments,
        "prospect_id": card.prospect_id,
        "created_at": card.created_at.isoformat() if card.created_at else None,
        "updated_at": card.updated_at.isoformat() if card.updated_at else None,
    }


def _parse_card_markdown(description, card_title):
    """Extract prospect fields from the card's markdown description.

    Supports two formats found in the research briefs:
      1. Markdown table: | Field | Value |
      2. Bold key-value:  **Key:** Value
    Falls back to card title for business_name.
    """
    result = {
        "business_name": _extract_business_name(description, card_title),
        "contact_name": None,
        "contact_email": None,
        "contact_phone": None,
        "source": "other",
        "source_url": None,
        "demo_url": None,
    }

    # --- Table format extraction ---
    table_patterns = {
        "contact_name": r"\|\s*Owner\s*\|\s*(.+?)\s*\|",
        "contact_phone": r"\|\s*Phone\s*\|\s*(.+?)\s*\|",
    }
    for field, pattern in table_patterns.items():
        m = re.search(pattern, description, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            if val and "NOT FOUND" not in val.upper() and "verify" not in val.lower():
                result[field] = val

    # --- Bold key-value extraction (fallbacks) ---
    bold_patterns = {
        "contact_name": r"\*\*Owner(?:/Decision Maker)?:\*\*\s*(.+)",
        "contact_phone": r"\*\*Phone:\*\*\s*(.+)",
    }
    for field, pattern in bold_patterns.items():
        if not result[field]:
            m = re.search(pattern, description)
            if m:
                val = m.group(1).strip()
                if val and "NOT FOUND" not in val.upper():
                    result[field] = val

    # --- Email extraction ---
    email_patterns = [
        r"\|\s*Email\s*\|\s*(.+?)\s*\|",
        r"\*\*Email:\*\*\s*(\S+)",
    ]
    for pattern in email_patterns:
        m = re.search(pattern, description, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            if "@" in val and "NOT FOUND" not in val.upper():
                result["contact_email"] = val
                break

    # --- Source detection: Facebook URL ---
    fb_patterns = [
        r"\|\s*Facebook\s*\|\s*\[?(?:[^\]]*\]\()?(https?://(?:www\.)?facebook\.com/\S+?)[\s\)|\|]",
        r"\[Facebook\]\((https?://(?:www\.)?facebook\.com/\S+?)\)",
        r"(https?://(?:www\.)?facebook\.com/[^\s\)|\]]+)",
    ]
    for pattern in fb_patterns:
        m = re.search(pattern, description)
        if m:
            result["source"] = "facebook"
            result["source_url"] = m.group(1).rstrip("|).> ")
            break

    # --- Source fallback: Google Maps URL ---
    if result["source"] == "other":
        maps_patterns = [
            r"\|\s*Google Maps\s*\|\s*\[?(?:[^\]]*\]\()?(https?://(?:www\.)?google\.com/maps\S+?)[\s\)|\|]",
            r"(https?://(?:www\.)?google\.com/maps/\S+)",
        ]
        for pattern in maps_patterns:
            m = re.search(pattern, description)
            if m:
                result["source"] = "google_maps"
                result["source_url"] = m.group(1).rstrip("|).> ")
                break

    # --- Demo URL extraction ---
    demo_patterns = [
        r"\*\*(?:Demo|Preview)\s*URL:\*\*\s*(\S+)",
        r"\|\s*(?:Demo|Preview)\s*(?:URL)?\s*\|\s*(\S+?)\s*\|",
    ]
    for pattern in demo_patterns:
        m = re.search(pattern, description, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            if val.startswith("http"):
                result["demo_url"] = val
                break

    return result


def _extract_business_name(description, card_title):
    """Get the business name from markdown or fall back to card title."""
    # Try table format: | Name | Value |
    m = re.search(r"\|\s*Name\s*\|\s*(.+?)\s*\|", description)
    if m:
        name = m.group(1).strip()
        if name and "NOT FOUND" not in name.upper():
            return name

    # Try bold format: **Business Name:** Value  or  **Business:** Value
    m = re.search(r"\*\*Business(?: Name)?:\*\*\s*(.+)", description)
    if m:
        name = m.group(1).strip()
        if name and "NOT FOUND" not in name.upper():
            return name

    # Fall back to card title, stripping " — category" or " - category" suffix
    name = re.split(r"\s*[—–-]\s*", card_title, maxsplit=1)[0].strip()
    # Also strip trailing bracket tags like " [A]" or " (85)"
    name = re.sub(r"\s*[\[\(][^\]\)]*[\]\)]\s*$", "", name).strip()
    return name or card_title
