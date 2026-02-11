"""Storage service — file uploads to Supabase Storage (prod) or local disk (dev).

Supabase bucket: ticket-attachments (must be created in Supabase dashboard).
Local fallback: instance/uploads/ directory.

Provides a unified interface for uploading and retrieving files.
"""

import logging
import os
import uuid

import requests
from flask import current_app

logger = logging.getLogger(__name__)

# Max file size: 10 MB
MAX_FILE_SIZE = 10 * 1024 * 1024

# Allowed MIME types
ALLOWED_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/heic",
    "application/pdf",
}

ALLOWED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".pdf",
}


def _get_supabase_config():
    """Return Supabase storage config if available, else None."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    bucket = os.environ.get("SUPABASE_STORAGE_BUCKET", "ticket-attachments")

    if url and key:
        return {"url": url.rstrip("/"), "key": key, "bucket": bucket}
    return None


def validate_file(file):
    """Validate an uploaded file (from request.files).

    Returns (ok: bool, error: str|None).
    """
    if not file or not file.filename:
        return False, "No file selected."

    # Check extension
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return False, f"File type '{ext}' is not allowed. Accepted: images and PDFs."

    # Check content type
    if file.content_type and file.content_type not in ALLOWED_TYPES:
        # Some browsers report wrong content types, so also check extension
        pass

    # Check file size (read + seek back)
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)

    if size > MAX_FILE_SIZE:
        return False, f"File is too large ({size / (1024*1024):.1f} MB). Maximum is 10 MB."

    if size == 0:
        return False, "File is empty."

    return True, None


def upload_file(file, ticket_id, message_id):
    """Upload a file and return metadata dict.

    Args:
        file: Werkzeug FileStorage from request.files
        ticket_id: The ticket this attachment belongs to
        message_id: The message this attachment belongs to

    Returns dict with:
        filename: original filename
        storage_path: path in bucket or on disk
        content_type: MIME type
        file_size: bytes
        public_url: URL to access the file
    """
    original_name = file.filename
    ext = os.path.splitext(original_name)[1].lower()
    safe_name = f"{uuid.uuid4().hex}{ext}"
    storage_path = f"{ticket_id}/{message_id}/{safe_name}"

    # Read file data
    file_data = file.read()
    file_size = len(file_data)
    content_type = file.content_type or "application/octet-stream"

    # Try Supabase first, fall back to local
    supabase = _get_supabase_config()
    if supabase:
        public_url = _upload_supabase(supabase, storage_path, file_data, content_type)
    else:
        public_url = _upload_local(storage_path, file_data)

    return {
        "filename": original_name,
        "storage_path": storage_path,
        "content_type": content_type,
        "file_size": file_size,
        "public_url": public_url,
    }


def _upload_supabase(config, path, data, content_type):
    """Upload to Supabase Storage. Returns public URL."""
    url = f"{config['url']}/storage/v1/object/{config['bucket']}/{path}"

    headers = {
        "Authorization": f"Bearer {config['key']}",
        "Content-Type": content_type,
        "x-upsert": "true",
    }

    try:
        resp = requests.post(url, headers=headers, data=data, timeout=30)
        resp.raise_for_status()

        # Build public URL
        public_url = f"{config['url']}/storage/v1/object/public/{config['bucket']}/{path}"
        logger.info(f"Uploaded to Supabase: {path}")
        return public_url

    except Exception as e:
        logger.error(f"Supabase upload failed: {e}")
        # Fall back to local
        return _upload_local(path, data)


def _upload_local(path, data):
    """Upload to local filesystem (dev fallback). Returns URL path."""
    upload_dir = os.path.join(
        current_app.instance_path, "uploads", os.path.dirname(path)
    )
    os.makedirs(upload_dir, exist_ok=True)

    filepath = os.path.join(current_app.instance_path, "uploads", path)
    with open(filepath, "wb") as f:
        f.write(data)

    logger.info(f"Uploaded locally: {filepath}")
    # Return a URL path that our Flask app can serve
    return f"/uploads/{path}"


def delete_file(storage_path):
    """Delete a file from storage. Best-effort, does not raise."""
    supabase = _get_supabase_config()
    if supabase:
        try:
            url = f"{supabase['url']}/storage/v1/object/{supabase['bucket']}/{storage_path}"
            headers = {"Authorization": f"Bearer {supabase['key']}"}
            requests.delete(url, headers=headers, timeout=10)
        except Exception as e:
            logger.warning(f"Failed to delete from Supabase: {e}")
    else:
        filepath = os.path.join(current_app.instance_path, "uploads", storage_path)
        try:
            os.remove(filepath)
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.warning(f"Failed to delete local file: {e}")
