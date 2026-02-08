"""Local development entry point.

Usage:
    python run.py
    python3 run.py
    /usr/local/bin/python3 run.py

The script detects if it's running outside the project virtualenv
and re-launches itself with the correct Python automatically.
"""

import os
import sys
import subprocess

# ── Auto-activate virtualenv ──
_project_dir = os.path.dirname(os.path.abspath(__file__))
_venv_python = os.path.join(_project_dir, "venv", "bin", "python")

if os.path.exists(_venv_python) and os.path.realpath(sys.executable) != os.path.realpath(_venv_python):
    print(f"[run.py] Switching to venv Python...")
    try:
        sys.exit(subprocess.call([_venv_python] + sys.argv))
    except KeyboardInterrupt:
        sys.exit(0)

# ── Normal startup ──
from dotenv import load_dotenv

load_dotenv()  # Load .env before anything else

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5001)
