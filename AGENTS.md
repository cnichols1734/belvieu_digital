# AGENTS.md

## Cursor Cloud specific instructions

### Overview

WaaS Portal — a Flask application for managing small business website clients. See `CLAUDE.md` for comprehensive architecture documentation, route reference, and code conventions.

### Running Tests

Tests are fully self-contained (in-memory SQLite, mocked Stripe, no `.env` needed):

```bash
source venv/bin/activate
FLASK_ENV=testing python -m pytest tests/ -v --tb=short
```

All 185 tests should pass. No external services or credentials are required.

### Running the Dev Server

The dev server uses a local SQLite database at `/workspace/instance/dev.db`. A `.env` file must exist with at minimum `SECRET_KEY`, `DATABASE_URL`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_BASIC_PRICE_ID`, and `APP_BASE_URL` (fake values work for local dev — Stripe calls will fail but the app starts and renders pages).

```bash
source venv/bin/activate
flask db upgrade        # apply migrations (idempotent)
flask seed-admin        # seed admin user + demo data (creates duplicates if run multiple times)
python run.py           # starts on port 5001
```

Admin login: `admin@waas.local` / `admin123`

### Important Gotchas

- **SQLite path resolution**: Flask-SQLAlchemy resolves relative SQLite URIs relative to the Flask instance path (`instance/`), not CWD. Use absolute paths in `DATABASE_URL` / `DATABASE_DIRECT_URL` (e.g. `sqlite:////workspace/instance/dev.db`) to avoid migration/runtime path mismatches.
- **`python3.12-venv`**: The system Python 3.12 may not ship with `ensurepip`. Install `python3.12-venv` via apt if `python3 -m venv` fails.
- **No lint tool configured**: The project has no ESLint/flake8/ruff config. There is no dedicated lint command — focus on tests and the dev server for verification.
- **`flask seed-admin` is not idempotent for all data**: The admin user check is idempotent, but prospect/workspace/site/invite records are re-created on each run. This is harmless for dev but can create duplicate demo data.
