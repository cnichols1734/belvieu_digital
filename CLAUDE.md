# CLAUDE.md — WaaS Portal

Context for AI assistants working on this repository. Read this before making any changes.

## Project Overview

**WaaS (Website-as-a-Service) portal** for Belvieu Digital. The business finds small businesses (via Google Maps / Facebook) with no website or a poor one, builds a custom one-pager, pitches it with a live `.dev` preview link, then converts them to paying clients at $59/month. An optional $250 one-time setup fee is charged (first month of hosting is free with setup) — controlled by the `PROMO_NO_SETUP_FEE` env var.

**Live domain:** `https://portal.belvieudigital.com`

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12 + Flask (application factory pattern) |
| Database | Supabase Postgres (prod) / SQLite in-memory (tests) |
| ORM | Flask-SQLAlchemy + Flask-Migrate (Alembic) |
| Auth | Flask-Login + invite-only registration (no self-signup) |
| Payments | Stripe (Checkout, Customer Portal, Webhooks) |
| Email | Google Workspace SMTP via `smtplib` |
| Hosting | Railway (Nixpacks builder, 2 Gunicorn workers) |
| Frontend | Server-rendered Jinja2, vanilla JS + CSS (no React/SPA) |
| Forms | Plain HTML forms with manual CSRF tokens (no WTForms form classes) |
| Security | Flask-WTF CSRF, Flask-Limiter, bleach sanitization, security headers |

## Repository Structure

```
belvieu_digital/
├── app/
│   ├── __init__.py          # create_app() factory — extensions, blueprints, CLI, headers
│   ├── config.py            # DevConfig / TestConfig / ProdConfig + validate()
│   ├── extensions.py        # Deferred extension instances (db, migrate, login, csrf, limiter)
│   ├── decorators.py        # @login_required_for_site, @admin_required
│   ├── blueprints/
│   │   ├── auth.py          # /auth/* — login, register (invite-gated), logout, password reset
│   │   ├── portal.py        # /<site_slug>/* — client dashboard, ticket list/new/detail/reply
│   │   ├── billing.py       # /<site_slug>/billing/* — Stripe Checkout, portal, domain search
│   │   ├── admin.py         # /admin/* — prospects CRM, workspaces, tickets (admin only)
│   │   ├── webhooks.py      # /stripe/webhooks — Stripe webhook handler (CSRF exempt)
│   │   ├── contact.py       # /contact — public contact form
│   │   └── form_relay.py    # /form-relay — external form submissions (CSRF exempt)
│   ├── models/
│   │   ├── __init__.py      # Imports all models (required for Alembic discovery)
│   │   ├── user.py          # User (UserMixin, email/password/is_admin/is_active)
│   │   ├── workspace.py     # Workspace + WorkspaceMember + WorkspaceSettings
│   │   ├── prospect.py      # Prospect (lite CRM, pipeline statuses)
│   │   ├── site.py          # Site (slug, URLs, status — presentation only)
│   │   ├── invite.py        # WorkspaceInvite (token, expiry, email lock)
│   │   ├── billing.py       # BillingCustomer + BillingSubscription
│   │   ├── stripe_event.py  # StripeEvent (idempotency deduplication)
│   │   ├── ticket.py        # Ticket + TicketMessage (state machine)
│   │   ├── audit.py         # AuditEvent (action log with metadata JSON)
│   │   ├── prospect_activity.py  # ProspectActivity (outreach + reminders)
│   │   └── contact_form.py  # ContactFormConfig (per-client form relay settings)
│   ├── services/
│   │   ├── billing_service.py   # DB sync helpers for billing (flush, no commit)
│   │   ├── stripe_service.py    # All Stripe API calls
│   │   ├── invite_service.py    # generate_invite (commits), validate_token, consume_invite
│   │   ├── ticket_service.py    # Ticket CRUD + state machine (flush, no commit)
│   │   ├── email_service.py     # send_email via Google SMTP
│   │   ├── domain_service.py    # WHOIS/RDAP domain availability checking
│   │   ├── storage_service.py   # Supabase Storage for ticket attachments
│   │   └── reminder_service.py  # D3/D10/D30 follow-up email logic
│   ├── middleware/
│   │   └── tenant.py        # resolve_tenant() — sets g.site/workspace/subscription/access_level
│   ├── static/
│   │   ├── css/style.css    # Full design system (600+ lines, Stripe-inspired, CSS vars)
│   │   ├── js/app.js        # Flash dismiss, confirm dialogs, copyInviteLink()
│   │   └── img/             # Images/icons
│   └── templates/
│       ├── base.html        # Layout shell (nav, flash messages, footer)
│       ├── landing.html     # Public landing page
│       ├── auth/            # login, register, forgot_password, reset_password
│       ├── portal/          # dashboard, billing, subscribe, suspended, tickets/
│       ├── admin/           # dashboard, prospects, workspaces, tickets, stripe_health
│       ├── emails/          # All transactional email templates
│       └── errors/          # 403, 404, 500
├── migrations/
│   ├── env.py               # Prefers DATABASE_DIRECT_URL; render_as_batch=True for SQLite
│   └── versions/            # Alembic migration files
├── tests/
│   ├── conftest.py          # App fixture, db_session (create/drop per test), seed_data
│   ├── test_auth.py         # 25 tests — registration, login, logout
│   ├── test_portal.py       # 9 tests — tenant resolution, dashboard access levels
│   ├── test_billing.py      # 12 tests — Stripe Checkout/Portal/webhook flows
│   ├── test_webhooks.py     # 10 tests — webhook signature, idempotency, event handlers
│   ├── test_tickets.py      # 32 tests — service layer + portal ticket routes
│   ├── test_admin.py        # 45 tests — all admin routes + auth guards
│   ├── test_security.py     # 19 tests — security headers + cross-tenant isolation
│   └── test_new_features.py # Additional feature tests
├── run.py                   # Local dev entry point (auto-activates venv, debug=True, port 5001)
├── Procfile                 # Railway: gunicorn on $PORT (2 workers) + reminder cron
├── railway.toml             # builder = "nixpacks"
├── requirements.txt         # All Python dependencies
├── memory.md                # Living project memory — full phase history and gotchas
└── reset_client_data.py     # Dev utility to reset client data in the database
```

## Local Development Setup

```bash
# 1. Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env — fill in SECRET_KEY, Stripe keys, SMTP credentials

# 4. Run database migrations
flask db upgrade

# 5. Seed admin + demo data
flask seed-admin

# 6. Start dev server (port 5001, debug mode)
python run.py

# 7. (Optional) Forward Stripe webhooks for local testing
stripe listen --forward-to localhost:5001/stripe/webhooks
```

## Running Tests

```bash
# All tests (uses in-memory SQLite, no real credentials needed)
python -m pytest tests/ -v

# Single file
python -m pytest tests/test_auth.py -v

# Single test
python -m pytest tests/test_auth.py::TestAuth::test_login_valid -v

# With short traceback
python -m pytest tests/ -v --tb=short
```

Tests use `FLASK_ENV=testing` which enables `TestConfig` (SQLite in-memory, CSRF disabled, rate limiting disabled, hardcoded fake Stripe keys). No `.env` file is needed to run the test suite. CI runs on every push/PR to `main` via `.github/workflows/tests.yml`.

## Flask CLI Commands

```bash
flask db upgrade             # Apply all Alembic migrations
flask db migrate -m "msg"    # Generate a new migration from model changes
flask seed-admin             # Create admin user + demo workspace/site/invite
flask create-setup-price     # Create one-time $250 setup fee in Stripe (run once)
flask verify-stripe-prices   # Verify configured Stripe price IDs exist
flask send-reminders         # Send D3/D10/D30 follow-up emails to pitched prospects
flask send-reminders --dry-run  # Preview what would be sent
```

## Key Architecture Concepts

### Application Factory
`create_app(config_name)` in `app/__init__.py`. Config name defaults to `FLASK_ENV` env var. Extensions are initialized with `init_app()` (deferred pattern). Models are imported inside `app.app_context()` for Alembic discovery.

### Multi-Tenant Design
Each client business is a **Workspace**. A Workspace has one **Site** (with a unique `site_slug`). Portal routes are prefixed `/<site_slug>/`. The **tenant middleware** (`app/middleware/tenant.py`) runs before every request and sets on Flask's `g`:
- `g.site` — the Site object
- `g.workspace` — the Workspace object
- `g.workspace_id` — the workspace UUID (use this, not `g.workspace.id`, to avoid detachment)
- `g.subscription` — the latest BillingSubscription (or `None`)
- `g.access_level` — one of `"full"` / `"read_only"` / `"blocked"` / `"subscribe"`

Access level logic:
| Subscription status | `g.access_level` |
|---|---|
| `active` or `trialing` | `"full"` |
| `past_due` | `"read_only"` |
| `canceled`, `unpaid`, `incomplete_expired` | `"blocked"` |
| No subscription | `"subscribe"` |

### Access Control Decorators
- `@login_required_for_site` — requires login + verified WorkspaceMember in `g.workspace_id`. Use on all portal routes.
- `@admin_required` — requires login + `current_user.is_admin == True`. Use on all admin routes.

### Invite-Only Registration
No self-registration. Admin creates prospect → converts → generates invite link (`/auth/register?token=<64-char-token>`). Invites can be email-locked or open. Tokens expire (45 days from conversion) and are single-use.

### Subscription Gating
- `site.status` is a **presentation-only** field (demo/active/paused/cancelled). Do NOT use it for access gating.
- `billing_subscriptions.status` is the source of truth. `g.access_level` (from tenant middleware) is the runtime check.
- Ticket list is accessible at **all** access levels — clients can always view existing tickets even if blocked/suspended.

### Stripe Integration
- Checkout: `POST /<slug>/billing/checkout` → `stripe_service.create_checkout_session()` → redirect to Stripe
- Customer Portal: `POST /<slug>/billing/portal` → `stripe_service.create_portal_session()` → redirect to Stripe
- Webhooks: `POST /stripe/webhooks` (CSRF exempt) — idempotency via `StripeEvent` table (deduplicates by `stripe_event_id`)
- Webhook handlers update `BillingSubscription`, `Site.status`, and log to `AuditEvent`

### Ticket State Machine
Defined by `Ticket.VALID_TRANSITIONS` dict on the model class. Enforced in `ticket_service.update_status()`. Auto-transition: when a non-admin user replies to a `waiting_on_client` ticket, status automatically moves to `in_progress`.

### Database Sessions
Service layer functions use a consistent commit pattern:
- **Flush, don't commit** — `ticket_service`, `billing_service` (except `get_or_create_billing_customer`)
- **Commit** — callers (blueprint routes) commit after service operations
- **Exception:** `invite_service.generate_invite()` commits immediately; `invite_service.consume_invite()` does NOT

### CSRF Handling
Forms use a manual hidden input — NOT WTForms form classes:
```html
<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
```
`TestConfig` sets `WTF_CSRF_ENABLED = False`. Webhooks blueprint and form relay blueprint are CSRF-exempt.

### Security Headers
Added via `@app.after_request` in `create_app()`. CSP allows Stripe JS/API, Google Fonts. HSTS only set in production (`not app.debug`). `unsafe-inline` is required for scripts (billing redirect) and styles (inline SVG).

## Data Models

| Model | Table | Key Fields |
|---|---|---|
| `User` | `users` | id (UUID), email, password_hash, is_admin, is_active |
| `Workspace` | `workspaces` | id (UUID), name, prospect_id (circular FK with use_alter) |
| `WorkspaceMember` | `workspace_members` | user_id, workspace_id, role (owner/member) |
| `WorkspaceSettings` | `workspace_settings` | workspace_id, brand_color, plan_features JSON, update_allowance, notification_prefs JSON |
| `Prospect` | `prospects` | id, business_name, contact info, source, status (researching→site_built→pitched→converted→declined), workspace_id |
| `Site` | `sites` | id, workspace_id, site_slug (unique), published_url, custom_domain, status (presentation only), domain_choice |
| `WorkspaceInvite` | `workspace_invites` | id, workspace_id, site_id, email (nullable=open invite), token (64-char), expires_at, used_at |
| `BillingCustomer` | `billing_customers` | workspace_id, stripe_customer_id (unique) |
| `BillingSubscription` | `billing_subscriptions` | workspace_id, stripe IDs, plan, status, period_end, cancel_at_period_end |
| `StripeEvent` | `stripe_events` | stripe_event_id (unique), event_type — for idempotency |
| `Ticket` | `tickets` | workspace_id, site_id, author_user_id, assigned_to_user_id, subject, category, status (state machine), priority, last_activity_at |
| `TicketMessage` | `ticket_messages` | ticket_id, author_user_id, message, is_internal |
| `AuditEvent` | `audit_events` | workspace_id, actor_user_id, action, metadata_ JSON |
| `ProspectActivity` | `prospect_activities` | prospect_id, activity_type, sent_at |
| `ContactFormConfig` | `contact_form_configs` | workspace_id, per-client form relay config |

**All primary keys are UUIDs** (`str(uuid.uuid4())`). All timestamps are timezone-aware.

**Circular FK:** `prospects.workspace_id` and `workspaces.prospect_id` both point at each other. The models use `use_alter=True` with named constraints. Do not change this without updating the Alembic migration.

## Migrations

```bash
# Always use DATABASE_DIRECT_URL for migrations (pooler can't handle DDL)
# The Alembic env.py prefers DATABASE_DIRECT_URL automatically

# After changing a model:
flask db migrate -m "describe the change"
flask db upgrade

# env.py has render_as_batch=True for SQLite compatibility in tests
```

Migration files live in `migrations/versions/`. Never edit applied migrations — always create new ones.

## Blueprint Route Reference

### Auth (`/auth/`)
| Method | Route | Name | Notes |
|---|---|---|---|
| GET/POST | `/auth/login` | `auth.login` | `?next=/<slug>/dashboard` |
| GET/POST | `/auth/register` | `auth.register` | `?token=<invite_token>` required |
| GET | `/auth/logout` | `auth.logout` | |
| GET/POST | `/auth/forgot-password` | `auth.forgot_password` | |
| GET/POST | `/auth/reset-password/<token>` | `auth.reset_password` | |

### Portal (`/<site_slug>/`)
| Method | Route | Name | Notes |
|---|---|---|---|
| GET | `/<slug>/` | `portal.site_root` | Redirects to dashboard |
| GET | `/<slug>/dashboard` | `portal.dashboard` | Requires `@login_required_for_site` |
| GET | `/<slug>/tickets` | `portal.ticket_list` | Accessible at all access levels |
| GET/POST | `/<slug>/tickets/new` | `portal.ticket_new` | Requires `access_level == "full"` |
| GET | `/<slug>/tickets/<id>` | `portal.ticket_detail` | Workspace isolation check |
| POST | `/<slug>/tickets/<id>/reply` | `portal.ticket_reply` | Requires `access_level == "full"` |

### Billing (`/<site_slug>/billing/`)
| Method | Route | Name | Notes |
|---|---|---|---|
| GET | `/<slug>/billing` | `billing.billing_overview` | |
| POST | `/<slug>/billing/checkout` | `billing.checkout` | Validates price_id against config |
| GET | `/<slug>/billing/success` | `billing.checkout_success` | 5s auto-redirect |
| GET | `/<slug>/billing/cancel` | `billing.checkout_cancel` | |
| POST | `/<slug>/billing/portal` | `billing.customer_portal` | Requires BillingCustomer |
| POST | `/<slug>/domain/check` | `billing.domain_check` | AJAX |
| POST | `/<slug>/domain/select` | `billing.domain_select` | AJAX |

### Admin (`/admin/`)
All routes require `@admin_required`. See the docstring in `app/blueprints/admin.py` for the full route map.

### Webhooks
| Method | Route | Notes |
|---|---|---|
| POST | `/stripe/webhooks` | CSRF exempt; verifies Stripe signature |

### Other
| Method | Route | Blueprint | Notes |
|---|---|---|---|
| GET/POST | `/contact` | `contact` | Public contact form |
| POST | `/form-relay/<token>` | `form_relay` | CSRF exempt; external client websites |

## Frontend Conventions

- **No framework** — server-rendered Jinja2 templates, vanilla JS
- **CSS design system** — `app/static/css/style.css` is 600+ lines of CSS custom properties. Do not rewrite; extend with new classes. Key patterns:
  - Layout: `.stats-grid` > `.stat-card`, `.content-grid`, `.pricing-grid` > `.pricing-card`
  - Components: `.cta-page`, `.subscription-card`, `.alert`, `.empty-state`, `.table-container` > `.table`
  - Badges: `.badge` + `.badge-dot` + modifier class (e.g. `.badge-active`, `.badge-basic`)
  - Buttons: `.btn-primary`, `.btn-secondary`, `.btn-danger`, `.btn-ghost`, `.btn-lg`, `.btn-icon`
  - Forms: `.form-group`, `.form-label`, `.form-control`, `.form-hint`
  - Navigation: `.back-link` for breadcrumb-style back links
- **CSRF in templates** — use `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">` in every POST form
- **Flash messages** — use `flash("message", "success"|"error"|"info"|"warning")`
- **Heading style** — use sentence case (not Title Case) in all headings
- **Inline `{% block scripts %}` only for page-specific JS** — global JS goes in `app.js`

## Testing Conventions

- Tests use `pytest` with `tests/conftest.py` fixtures
- `db_session` fixture is `autouse=True` — runs for every test automatically; creates all tables before, drops after
- `seed_data` fixture — use its plain string IDs (`seed_data["workspace_id"]`, `seed_data["site_slug"]`) when accessing objects across `app_context` boundaries to avoid `DetachedInstanceError`
- Mock Stripe calls with `@patch("app.services.stripe_service.stripe")` targeting the import location, not the global package
- `TestConfig.SERVER_NAME = "localhost"` — required for `url_for()` in tests without a request context
- Rate limiting is disabled in tests via `RATELIMIT_ENABLED = False` in TestConfig
- Always add tests for new routes — auth guards, happy path, error cases, access level gating

## Environment Variables

See `.env.example` for the full list. Variables required at startup (validated by `Config.validate()`):

| Variable | Description |
|---|---|
| `SECRET_KEY` | Flask session secret (min 32 random bytes) |
| `DATABASE_URL` | Supabase session pooler URL (for runtime) |
| `DATABASE_DIRECT_URL` | Supabase direct/transaction URL (for Alembic migrations) |
| `STRIPE_SECRET_KEY` | Stripe API key (`sk_test_...` or `sk_live_...`) |
| `STRIPE_PUBLISHABLE_KEY` | Stripe publishable key (`pk_test_...`) |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook signing secret (`whsec_...`) |
| `STRIPE_BASIC_PRICE_ID` | Stripe Price ID for Basic plan ($59/mo) |
| `STRIPE_SETUP_PRICE_ID` | Stripe Price ID for one-time setup fee ($250) — not required when `PROMO_NO_SETUP_FEE=true` |
| `APP_BASE_URL` | Full URL of the app (e.g. `https://portal.belvieudigital.com`) |
| `MAIL_USERNAME` | Google Workspace email address |
| `MAIL_PASSWORD` | Google App Password (not account password) |
| `PROMO_NO_SETUP_FEE` | Set to `true` to waive the $250 setup fee site-wide |
| `SUPABASE_URL` | Supabase project URL (for Storage) |
| `SUPABASE_SERVICE_KEY` | Supabase `service_role` key (for Storage) |
| `SUPABASE_STORAGE_BUCKET` | Bucket name for ticket attachments (default: `ticket-attachments`) |

`postgres://` URLs are automatically rewritten to `postgresql://` in `config.py` for SQLAlchemy compatibility.

## Deployment (Railway)

- Builder: Nixpacks (auto-detects Python)
- Web process: `gunicorn "app:create_app()" --bind 0.0.0.0:$PORT --workers 2`
- Cron process: `flask send-reminders` (for prospect follow-up emails)
- Production config activates when `FLASK_ENV=production`
- Production uses a larger SQLAlchemy connection pool (`pool_size=5`, `max_overflow=10`)
- HSTS header is only added in production (when `app.debug` is False)

For Flask-Limiter in production with multiple workers, switch from `memory://` to a Redis `storage_uri` to share rate limit state across workers.

## Important Gotchas

1. **Circular FK (prospects ↔ workspaces)** — both tables have FKs to each other. Models use `use_alter=True`. Do not change without updating the migration.

2. **`site.status` is presentation-only** — never gate access on it. Use `g.access_level` (derived from `billing_subscriptions.status`) instead.

3. **Tenant middleware registration order** — must be registered BEFORE blueprints in `create_app()`. It runs via `app.before_request()`.

4. **`from app import models` (not `import app.models`)** — inside `create_app()`'s `app_context()`. Using `import app.models` would shadow the local `app` Flask instance variable.

5. **`AuditEvent.metadata_`** — Python attribute name (avoids conflict with Python's builtin `metadata`), but DB column is `metadata`.

6. **`invite_service` commit behavior** — `generate_invite()` commits immediately; `consume_invite()` does NOT (caller commits as part of a larger transaction).

7. **`billing_service` commit behavior** — most functions flush only; `get_or_create_billing_customer()` commits immediately (needed so the customer ID exists for Stripe).

8. **`db.session.get(Model, id)` not `Model.query.get(id)`** — the latter is deprecated in SQLAlchemy 2.0.

9. **SQLite timezone handling** — `WorkspaceInvite.is_expired` handles both naive (SQLite in tests) and aware (Postgres in prod) datetimes by adding UTC tzinfo to naive datetimes before comparison.

10. **Flask-Login `user_loader`** — defined in `extensions.py` with a lazy import of `User` to avoid circular imports.

11. **Rate limiting** — uses `memory://` storage (in-process). With multiple Gunicorn workers this means each worker has independent counters — switch to Redis for true rate limiting across workers.

12. **CSRF manual tokens** — no WTForms form classes are used. Every POST form needs the hidden CSRF input. `csrf.exempt()` is called for the webhooks and form_relay blueprints.
