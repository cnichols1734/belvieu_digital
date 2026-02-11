# WaaS Portal — Living Memory

> This document is context for future AI sessions. Feed this + the plan file to pick up where we left off.

## Tools Available

- **Context7 MCP** — use `resolve-library-id` + `query-docs` to look up current documentation for any library (Flask, Stripe, SQLAlchemy, etc.) when you need up-to-date API references or examples.

## Project Overview

WaaS (Website-as-a-Service) portal for Chris's business: find small businesses on Google Maps / Facebook with no site or a bad one, build them a custom one-pager, pitch them with a live .dev preview link, convert them to paying clients with a $250 one-time setup fee + $59/mo (first month free with setup).

**Stack:** Flask, Supabase Postgres, Stripe, Railway. Server-rendered HTML (Jinja), vanilla JS + CSS. No React, no SPA.

## Plan Location

`.cursor/plans/waas_portal_mvp_ec9c9aaf.plan.md` — the full v3 plan with 9 phases (0-8). Always refer back to this for specs.

## Environment / Credentials

- **Stripe account:** "Belvieu Digital sandbox" (`acct_1SyQCA3E1rMCjOFG`), test mode
- **Stripe CLI** installed via Homebrew (`stripe` v1.35.0), authenticated. Session expires after 90 days.
- **Stripe products created in test mode:**
  - WaaS Monthly — $59/mo — Product: `prod_TwKBB8dPngYZ1f`, Price: `price_1SyRX13E1rMCjOFGiCt4XvzM`
  - Website Setup Fee — $250 one-time — Run `flask create-setup-price` to create, set STRIPE_SETUP_PRICE_ID env var
- **Webhook listener:** run `stripe listen --forward-to localhost:5000/stripe/webhooks` each dev session. The `whsec_` signing secret in `.env` matches this CLI listener.
- **Local dev DB:** SQLite (`sqlite:///dev.db`). Switch to Supabase Postgres for production.
- **Supabase project:** `lynrxezjbafyrcgblhdl` (new, clean). Connection strings not yet configured — need DB password + region from Chris when ready for prod.
- **All secrets live in `.env`** (gitignored). Never commit `.env`.

## What's Done

### Phase 0: Project Scaffolding (COMPLETE)
- Git repo initialized
- Full directory tree created per plan
- `app/config.py` — DevConfig / ProdConfig, validates required env vars on startup
- `app/extensions.py` — SQLAlchemy, Migrate, LoginManager, CSRFProtect (deferred init pattern). Includes `user_loader` for Flask-Login.
- `app/__init__.py` — `create_app()` factory with all 5 blueprints registered, error handlers for 403/404/500
- `app/decorators.py` — `@login_required_for_site` (dual tenant check: g.workspace_id + membership) and `@admin_required`
- 5 blueprint stubs: auth, portal, billing, admin, webhooks — all return placeholder text
- `base.html` — layout shell with nav, flash messages, footer
- `style.css` — complete base stylesheet with CSS variables, cards, badges, forms, tables, responsive
- `app.js` — flash auto-dismiss, confirm dialogs
- Error pages: 403, 404, 500
- `.env.example` with all required vars (incl. DATABASE_DIRECT_URL)
- `requirements.txt`, `Procfile`, `railway.toml`, `README.md`

### Phase 1: Data Model and Migrations (COMPLETE)
- **13 tables across 9 model files** — all implemented with full relationships:
  - `user.py` — User (UserMixin, email/password/is_admin/is_active, relationships to memberships, tickets, audit)
  - `workspace.py` — Workspace, WorkspaceMember, WorkspaceSettings (brand_color, plan_features JSON, update_allowance, notification_prefs JSON)
  - `prospect.py` — Prospect (lite CRM: business_name, contact info, source, source_url, notes, demo_url, status pipeline, workspace FK)
  - `site.py` — Site (workspace FK, site_slug unique, display_name, published_url, custom_domain, status as presentation value)
  - `invite.py` — WorkspaceInvite (workspace+site FK, optional email lock, 64-char token, expires_at, used_at, helper properties: is_valid/is_expired/is_used)
  - `billing.py` — BillingCustomer (workspace FK, stripe_customer_id unique), BillingSubscription (workspace FK, stripe IDs, plan, status, period end, cancel flag)
  - `stripe_event.py` — StripeEvent (stripe_event_id unique for idempotency, event_type)
  - `ticket.py` — Ticket (workspace+site+author+assigned_to FKs, subject, description, category, status with VALID_TRANSITIONS dict, priority, last_activity_at), TicketMessage (ticket+author FKs, message, is_internal boolean)
  - `audit.py` — AuditEvent (workspace+actor FKs nullable, action, metadata JSON)
- `models/__init__.py` — imports all models for Alembic discovery
- **Alembic initialized** with `migrations/` folder
  - `env.py` updated to prefer `DATABASE_DIRECT_URL` for migrations (pooler causes DDL issues)
  - `env.py` has batch mode enabled for SQLite compatibility
  - Initial migration generated and applied: `cd77260a1e5a_initial_schema_13_tables.py`
  - Circular FK between prospects/workspaces handled with `use_alter=True` on models and `batch_alter_table` in migration
- **`flask seed-admin` CLI command** — creates admin user + demo prospect (converted) + workspace + workspace_settings + workspace_member + site (demo-pizza) + invite token (30-day expiry, email-locked)
- `create_app()` updated to import models for discovery and register CLI commands
- **Verified:** app boots clean, all 13 tables created with correct columns, seed data inserted, all relationships navigable in both directions

### Phase 2: Auth System (COMPLETE)
- **`app/services/invite_service.py`** — three functions:
  - `generate_invite(workspace_id, site_id, email=None, expires_days=30)` — creates invite row, commits. Returns WorkspaceInvite.
  - `validate_token(token)` — returns `(invite, None)` if valid, `(None, error_msg)` if invalid/expired/used.
  - `check_email_match(invite, email)` — returns `(True, None)` or `(False, error_msg)`. Only enforced if `invite.email` is set.
  - `consume_invite(invite)` — sets `used_at`, does NOT commit (caller commits as part of larger txn).
- **`app/blueprints/auth.py`** — full auth blueprint with 3 routes:
  - `GET/POST /auth/register?token=<invite_token>` — invite-gated registration. Validates token, checks email lock, creates User + WorkspaceMember (role=owner), consumes invite, logs audit event, logs in, redirects to `/<site_slug>/dashboard`.
  - `GET/POST /auth/login?next=/<slug>/dashboard` — email+password login. Checks is_active. Open redirect protection (only allows relative URLs in `next`). Passes `next` via both query param and hidden form field.
  - `GET /auth/logout` — clears session, redirects to login.
- **`app/templates/auth/login.html`** — login form (email, password, remember me, hidden next field). Uses `csrf_token()` hidden input.
- **`app/templates/auth/register.html`** — register form (full name, email, password). Shows error state (no form) if token is invalid/expired/used. Email field is readonly if invite is email-locked. Uses `csrf_token()` hidden input.
- **Auth CSS** — added to `style.css`: `.auth-container`, `.auth-card`, `.auth-title`, `.auth-subtitle`, `.auth-footer`, `.auth-error-state`, `.btn-full`, `.form-check`, `.check-label`.
- **`app/config.py`** — added `TestConfig` class: in-memory SQLite, CSRF disabled, hardcoded test values for all env vars, `validate()` is a no-op. Added `"testing"` to `config_by_name`.
- **`tests/conftest.py`** — full test fixture suite:
  - `app` fixture (session-scoped): creates app with "testing" config.
  - `db_session` fixture (autouse): creates all tables before each test, drops after. Returns `db.session`.
  - `client` fixture: Flask test client.
  - `seed_data` fixture: creates admin user, prospect, workspace, workspace_settings, workspace_member, site (slug="test-pizza"), and 4 invites (email-locked, open, expired, used). Returns dict with objects AND plain string IDs (`workspace_id`, `site_id`, `admin_id`, `site_slug`) to avoid DetachedInstanceError.
- **`tests/test_auth.py`** — 25 tests, all passing:
  - Registration: valid token, no token, invalid token, expired token, used token, open invite success, email-locked success, email mismatch, duplicate email, short password, missing fields, expired POST, used POST
  - Login: page loads, valid credentials, next param redirect, invalid password, nonexistent email, deactivated account, missing fields, open redirect prevention
  - Logout: logged in, not logged in
  - Authenticated redirects: login page, register page
- **`requirements.txt`** — added `pytest`

### Phase 3: Portal / Client Dashboard (COMPLETE)
- **`app/middleware/tenant.py`** — `resolve_tenant()` before_request hook + `init_tenant_middleware(app)`:
  - Extracts `site_slug` from `request.view_args`, skips non-portal routes (static/auth/admin/stripe)
  - Queries `Site` by slug, loads workspace, finds latest `BillingSubscription`
  - Sets on `g`: `site`, `workspace`, `workspace_id`, `subscription`, `access_level`
  - Access levels: `"full"` (active/trialing), `"read_only"` (past_due), `"blocked"` (canceled/unpaid/incomplete_expired), `"subscribe"` (no subscription)
  - Registered in `create_app()` via `init_tenant_middleware(app)` BEFORE blueprints
- **`app/blueprints/portal.py`** — 2 routes:
  - `GET /<site_slug>/` — redirects to dashboard (or login if unauthenticated)
  - `GET /<site_slug>/dashboard` — protected by `@login_required_for_site`. Renders different templates based on `g.access_level`: subscribe page (no sub), suspended page (blocked), dashboard (full/read_only). Loads recent 5 tickets for dashboard.
- **`app/templates/base.html`** — upgraded with portal-aware nav (shows Dashboard/Tickets links when `g.site` exists, Admin link for admins, user name + logout). Branded nav icon. SVG icons in flash messages. Fixed footer year to 2026.
- **`app/static/css/style.css`** — complete Stripe-inspired design system overhaul (600+ lines):
  - Full gray/indigo/green/yellow/red/blue color token system
  - Refined typography (14px base, -apple-system stack, antialiased)
  - Sticky nav, branded nav-icon, subtle nav-divider
  - Cards with `border-radius: 12px`, layered shadows
  - Stats grid (metric cards like Stripe dashboard)
  - Pricing grid with featured card treatment + "Most Popular" badge
  - Content grid (2-col responsive)
  - Badges with colored dots (`.badge-dot`)
  - Alert banners with SVG icons
  - Empty states
  - CTA pages (centered, icon + heading + body + button)
  - Subscription status card (flex row)
  - Table container with rounded corners
  - Select inputs with custom chevron
  - Ghost buttons, btn-lg, btn-icon
  - Full responsive breakpoints (768px, 480px)
- **`app/templates/portal/dashboard.html`** — client dashboard:
  - Welcome header with first name
  - Past-due warning banner (alert-warning with "Update payment" button)
  - Subscription status card (plan name, badge, renewal date, manage billing button)
  - Content grid: website info card (domain, preview URL, status badge) + recent tickets card (last 5 with status badges, empty state)
- **`app/templates/portal/suspended.html`** — subscription ended CTA page:
  - Centered layout with icon, heading, explanation, "Resubscribe" button
  - Reassurance message ("content is preserved")
- **`app/templates/portal/subscribe.html`** — pricing page:
  - Two plan cards (Basic $59/mo, Pro $99/mo) with feature lists
  - Pro card has "Most Popular" badge and featured border treatment
  - Each card has a checkout form (POST to billing route with price_id)
- **`tests/test_portal.py`** — 9 tests, all passing:
  - Tenant resolution: valid slug, invalid slug (404), root redirect
  - Dashboard: no subscription (subscribe page), active subscription (dashboard), past_due (warning), canceled (suspended), unauthenticated (redirect), non-member (403)

### Phase 4: Stripe Integration / Billing (COMPLETE)
- **`app/services/billing_service.py`** — DB sync helpers:
  - `get_plan_from_price_id(price_id, app_config)` — maps STRIPE_BASIC_PRICE_ID -> "basic", STRIPE_PRO_PRICE_ID -> "pro"
  - `get_or_create_billing_customer(workspace_id, stripe_customer_id)` — upserts BillingCustomer, commits immediately
  - `upsert_subscription(...)` — creates or updates BillingSubscription from Stripe data, flushes (does not commit)
  - `derive_site_status(workspace_id, subscription_status)` — maps sub status to site.status (presentation only)
  - `log_billing_audit(workspace_id, action, metadata)` — creates AuditEvent with actor_user_id=None (system)
  - `get_workspace_id_from_stripe_customer(stripe_customer_id)` — reverse lookup for invoice events
- **`app/services/stripe_service.py`** — all Stripe API interactions:
  - `create_checkout_session(workspace_id, site_id, price_id, site_slug)` — gets/creates Stripe Customer, creates checkout.Session with workspace/site metadata, returns session.url
  - `create_portal_session(workspace_id, site_slug)` — creates billing_portal.Session, returns session.url. Raises ValueError if no BillingCustomer.
  - `verify_webhook_signature(payload, sig_header)` — calls stripe.Webhook.construct_event
  - `handle_webhook_event(event)` — idempotency check via StripeEvent table, routes to handler, records event, commits. Returns (bool, str).
  - 5 event handlers: `_handle_checkout_completed`, `_handle_subscription_updated`, `_handle_subscription_deleted`, `_handle_payment_failed`, `_handle_payment_succeeded`
- **`app/blueprints/billing.py`** — 5 routes:
  - `POST /<slug>/billing/checkout` — validates price_id against config, creates Stripe Checkout Session, redirects to Stripe
  - `GET /<slug>/billing/success` — post-checkout landing with spinner + 5s auto-redirect to dashboard
  - `GET /<slug>/billing/cancel` — flashes info message, redirects to dashboard
  - `POST /<slug>/billing/portal` — creates Stripe Customer Portal Session, redirects to Stripe
  - `GET /<slug>/billing` — billing overview page (shows plan info + manage button, or subscribe page if no sub)
- **`app/blueprints/webhooks.py`** — Stripe webhook endpoint:
  - `POST /stripe/webhooks` — gets raw body, verifies signature, calls handle_webhook_event, returns JSON
  - CSRF exempted via `csrf.exempt(webhooks_bp)` in create_app()
- **Templates created:**
  - `portal/billing.html` — current plan card, status badge, renewal date, "Manage billing on Stripe" button
  - `portal/billing_success.html` — success checkmark, spinner, 5s auto-redirect to dashboard
- **Templates updated:**
  - `portal/subscribe.html` — form actions changed from `billing.billing_overview` to `billing.checkout`
  - `portal/dashboard.html` — "Manage billing" changed to POST form to `billing.customer_portal`; "Update payment" changed to POST form to `billing.customer_portal`
  - `portal/suspended.html` — "Resubscribe" link points to `billing.billing_overview` (renders subscribe page when no active sub)
- **CSS added:** `.billing-processing`, `.billing-spinner` with spin animation
- **`app/__init__.py`** — added `csrf.exempt(webhooks_bp)` after blueprint registration
- **Tests:** 56 (25 auth + 9 portal + 12 billing + 10 webhooks), all passing
  - `tests/test_billing.py` — 12 tests: checkout redirect, invalid/missing price_id, existing customer reuse, success page, cancel redirect, portal redirect, portal without customer, billing overview with/without sub, auth guards
  - `tests/test_webhooks.py` — 10 tests: missing/invalid signature, duplicate event idempotency, checkout.session.completed (full flow: creates sub + customer + site status + audit), subscription.updated (status + cancel_at_period_end), subscription.deleted (canceled + site paused), payment_failed (past_due), payment_succeeded (reactivates), unknown event accepted

### Phase 5: Ticketing System (COMPLETE)
- **`app/services/ticket_service.py`** — full ticket service layer:
  - `create_ticket(workspace_id, site_id, user_id, subject, description, category)` — creates ticket, sanitizes input with bleach, validates category, logs audit event, flushes (does not commit)
  - `add_message(ticket_id, user_id, message, is_internal=False)` — adds threaded reply, sanitizes with bleach, updates `last_activity_at`, auto-transitions `waiting_on_client` -> `in_progress` on client (non-admin) reply, logs audit
  - `update_status(ticket_id, new_status, actor_user_id)` — enforces `Ticket.VALID_TRANSITIONS` dict, raises ValueError on invalid transition, logs audit
  - `assign_ticket(ticket_id, assigned_to_user_id, actor_user_id)` — validates assignee is admin, logs audit
  - `get_ticket_with_messages(ticket_id, include_internal=False)` — loads ticket + messages, optionally filtering out internal notes
  - `list_tickets_for_workspace(workspace_id, status_filter=None)` — lists tickets ordered by `last_activity_at` desc
  - All functions use `db.session.get()` (not deprecated `Query.get()`)
  - `_sanitize(text)` helper strips all HTML tags via `bleach.clean(tags=[], strip=True)`
- **`app/blueprints/portal.py`** — expanded with 4 ticket routes:
  - `GET /<slug>/tickets` — ticket list, accessible at all access levels (full, read_only, blocked) so clients can always view existing tickets. Supports `?status=` filter param
  - `GET/POST /<slug>/tickets/new` — create ticket form. Requires `g.access_level == "full"`. Redirects blocked/read_only/subscribe users to ticket list with flash warning
  - `GET /<slug>/tickets/<id>` — ticket detail + message thread. Internal notes hidden from client view. Workspace isolation check (ticket must belong to `g.workspace_id`)
  - `POST /<slug>/tickets/<id>/reply` — add reply. Requires `g.access_level == "full"`. Client replies are never internal
- **Templates created (3):**
  - `portal/tickets/list.html` — ticket table with subject, category, status badge, priority badge, last activity date. Status filter tabs (All/Open/In Progress/Waiting/Done). Empty state with CTA to create ticket
  - `portal/tickets/new.html` — form with subject input, category dropdown (Content Update/Bug/Question), description textarea. Validation error handling with field preservation
  - `portal/tickets/detail.html` — ticket header (title, status badge, priority badge, metadata), original description as first message, threaded message list with avatar initials, admin messages have indigo left border + "Support" badge, reply form at bottom (hidden when ticket is done or access is not full), closed/blocked states with appropriate messaging
- **Templates updated:**
  - `base.html` — nav Tickets link now points to `portal.ticket_list` route (was placeholder). Shows for access levels full, read_only, and blocked (not subscribe)
  - `portal/dashboard.html` — "New ticket" button points to `portal.ticket_new`. Ticket rows are clickable links to `portal.ticket_detail`. "View all tickets" link at bottom. Nav Tickets link updated to real route
- **CSS added** to `style.css`:
  - `.ticket-row-link` — clickable ticket rows in dashboard card
  - `.ticket-filters` + `.ticket-filter-tab` — status filter tab bar with active underline
  - `.ticket-header`, `.ticket-header-top`, `.ticket-title`, `.ticket-badges`, `.ticket-meta` — detail page header
  - `.ticket-thread`, `.ticket-message`, `.ticket-message-admin`, `.ticket-message-client` — threaded message cards. Admin messages get indigo left border
  - `.ticket-message-avatar`, `.ticket-message-avatar-admin` — circular avatar with initial letter
  - `.ticket-message-author`, `.ticket-message-time`, `.ticket-message-body` — message content with pre-wrap whitespace
  - `.ticket-message-internal` — yellow background for internal notes (admin view, Phase 6)
  - `.ticket-reply`, `.ticket-reply-closed` — reply form card and closed ticket state
- **Tests:** 88 total (25 auth + 9 portal + 12 billing + 10 webhooks + 32 tickets), all passing
  - `tests/test_tickets.py` — 32 tests in two classes:
    - `TestTicketService` (16 tests): create ticket, HTML sanitization, invalid category, empty subject, add message, message sanitization, internal notes, auto-transition waiting_on_client->in_progress on client reply, NO auto-transition on admin reply, valid status transition, invalid status transition, done is terminal state, assign to admin, assign to non-admin fails, get_ticket_with_messages excludes internal, list with status filter
    - `TestTicketRoutes` (16 tests): list requires auth, list with active sub, blocked can still view list, list with status filter, create page loads, create submit, missing fields validation, blocked redirects, no sub redirects, detail view, internal notes hidden from client, wrong workspace denied, reply creates message, empty reply rejected, blocked user can't reply, reply auto-transitions waiting_on_client

### Phase 6: Admin Dashboard + Lite CRM (COMPLETE)
- **`app/blueprints/admin.py`** — full admin blueprint with 16 routes across 5 sections:
  - **Dashboard** (`GET /admin/`) — pipeline counts, MRR, active subs, open tickets, pending invites, conversion rate, recent activity feed from audit_events
  - **Prospects** — `prospect_list` (filterable by status), `prospect_new` (create form), `prospect_detail` (view), `prospect_update` (edit all fields + status), `prospect_convert` (GET form + POST creates workspace + site + settings + invite)
  - **Workspaces** — `workspace_list` (enriched with site/sub/invite data), `workspace_detail` (site, members, subscription, Stripe link, invites, tickets, settings), `workspace_invite` (generates new invite link)
  - **Tickets** — `ticket_list` (cross-workspace, filterable by status + assignee), `ticket_detail` (full thread with internal notes, admin controls sidebar), `ticket_reply` (with is_internal checkbox), `ticket_status` (enforces state machine), `ticket_assign` (assign/unassign)
  - **Site Override** — `site_status_override` (manual status change with audit)
  - All routes use `@admin_required` decorator
  - All state-changing actions log to `audit_events`
- **Templates created (11):**
  - `admin/dashboard.html` — stats grid (pipeline, active subs, MRR, open tickets, conversion rate), prospect pipeline card, quick actions card, recent activity feed
  - `admin/prospects.html` — pipeline table with status filter tabs, source/status badges, contact info, demo URL link
  - `admin/prospect_new.html` — form with business name, contact info, source dropdown, source URL, demo URL, notes textarea
  - `admin/prospect_detail.html` — editable form (left), quick sidebar (demo site link, source listing link, quick status buttons, convert CTA, workspace link if converted)
  - `admin/workspace_convert.html` — conversion form pre-filled from prospect (site slug, display name, published URL, custom domain, invite email lock)
  - `admin/workspace_convert_success.html` — success page with copyable invite link, workspace/site summary, JS copy-to-clipboard
  - `admin/workspaces.html` — table with workspace name, site slug, plan badge, subscription status, invite status (pending/used/expired), prospect back-link
  - `admin/workspace_detail.html` — site info + status override form, members list, subscription details + Stripe dashboard link, invite history + generate new invite form, recent tickets, workspace settings (brand color, update allowance)
  - `admin/workspace_invite_success.html` — invite link display with copy button
  - `admin/tickets.html` — cross-workspace ticket table with status filter tabs + assignee dropdown, workspace link, priority/status badges
  - `admin/ticket_detail.html` — full thread (original description + messages with internal notes in yellow), reply form with internal note checkbox, sidebar controls (status dropdown, priority display, assignment dropdown, ticket metadata)
- **Templates updated (1):**
  - `base.html` — admin nav link uses `url_for('admin.dashboard')` instead of hardcoded `/admin/`
- **CSS added** to `style.css` (~120 lines):
  - `.admin-pipeline-list/row/count` — pipeline card with hover effect
  - `.admin-actions-list`, `.admin-pending-stat` — quick actions card
  - `.admin-activity-feed/item/action/meta` — scrollable activity feed
  - `.admin-detail-row/label` — key-value detail rows for workspace/ticket detail
  - `.admin-invite-link-box` — invite link input with copy button
  - `.admin-ticket-filters`, `.admin-assignee-filter` — combined status tabs + assignee dropdown
  - `.admin-status-actions` — quick status change buttons
  - Badge colors for pipeline statuses: `.badge-researching`, `.badge-site_built`, `.badge-pitched`, `.badge-converted`, `.badge-declined`
  - Badge colors for sources: `.badge-google_maps`, `.badge-facebook`, `.badge-referral`, `.badge-other`
  - Badge colors for priorities: `.badge-low`, `.badge-normal`, `.badge-high`
  - Badge colors for plans: `.badge-basic`, `.badge-pro`
  - `.font-mono` utility
- **Tests:** 133 total (25 auth + 9 portal + 12 billing + 10 webhooks + 32 tickets + 45 admin), all passing
  - `tests/test_admin.py` — 45 tests in 6 classes:
    - `TestAdminAuthGuards` (5 tests): unauthenticated redirect, non-admin 403 on dashboard/prospects/workspaces/tickets
    - `TestAdminDashboard` (3 tests): loads, pipeline counts, MRR display
    - `TestAdminProspects` (12 tests): list, filter by status, empty filter, new form loads, create success, missing name, invalid source, detail loads, detail not found, update, convert form loads, convert success (full flow), duplicate slug rejection, already converted
    - `TestAdminWorkspaces` (7 tests): list loads, detail loads, detail not found, shows members, shows invites, generate invite with email, generate open invite
    - `TestAdminTickets` (12 tests): list loads, filter by status, filter unassigned, detail loads, shows internal notes, not found, reply, internal reply, empty reply, status change, invalid status transition, assign, unassign
    - `TestAdminSiteOverride` (3 tests): status override, invalid status, site not found

### Phase 7: Security Hardening and Polish (COMPLETE)
- **Security headers middleware** — `after_request` handler in `create_app()` adds:
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `Referrer-Policy: strict-origin-when-cross-origin`
  - `X-XSS-Protection: 1; mode=block`
  - `Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=(self)`
  - `Content-Security-Policy` with directives for self, Stripe JS/API/checkout/billing, unsafe-inline for script/style
  - `Strict-Transport-Security` (production only, not in debug mode)
- **Flask-Limiter** — rate limiting on auth routes:
  - Added `Flask-Limiter` to requirements.txt and extensions.py
  - `limiter` instance with `get_remote_address` key function, `memory://` storage
  - `POST /auth/login`: 15 per minute
  - `POST /auth/register`: 10 per minute
  - `RATELIMIT_ENABLED = False` in TestConfig to avoid interfering with tests
  - `limiter.init_app(app)` in `create_app()`
- **Cross-tenant isolation tests** — `tests/test_security.py` with 19 tests:
  - `TestSecurityHeaders` (8 tests): X-Content-Type-Options, X-Frame-Options, Referrer-Policy, X-XSS-Protection, Permissions-Policy, CSP, no HSTS in debug, headers on error pages
  - `TestCrossTenantIsolation` (10 tests): creates two separate workspaces with users and subscriptions. Tests: User A cannot access Workspace B dashboard (403), User B cannot access Workspace A dashboard (403), User A cannot view B's tickets (403), User A cannot view B's ticket detail (redirected with "Ticket not found"), User A cannot reply to B's ticket, User A cannot create ticket in B's workspace (403), B's ticket data not in A's dashboard, unauthenticated redirect, sanity checks (A can access own workspace, A can view own ticket)
  - `TestRateLimiting` (1 test): verifies limiter is initialized with RATELIMIT_ENABLED=False in test config
- **UI Polish — CSS overhaul:**
  - Refined `--color-bg` from `--gray-50` to `#f6f8fa` for more subtle background
  - Added `--shadow-ring` token for consistent focus rings
  - Added `--transition` CSS variable for consistent animation timing
  - Nav uses `backdrop-filter: blur(8px)` for glassmorphism effect
  - Buttons have `transform: scale(0.98)` on `:active` for tactile feedback
  - Pricing cards have `translateY(-2px)` hover lift
  - Flash messages have `flash-in` keyframe animation
  - Tables have row transition effects
  - Stat cards have hover elevation
  - Added `::selection` styling with indigo colors
  - Added `.back-link` component (arrow + text, used across portal pages)
  - Added `.site-info-item`, `.site-info-label`, `.site-info-value` for dashboard website card (replaces inline form-group usage)
  - Added `.external-link-icon` utility class
  - Error pages: new `.error-page-code` class with gradient text effect, `.error-page-icon` for SVG icons
  - Better mobile breakpoints: ticket filters get horizontal scroll on mobile, ticket header stacks vertically, admin ticket filters stack
  - Added scrollbar hiding for mobile filter tabs
- **UI Polish — Templates cleaned:**
  - Removed dead `{% block nav_links %}` blocks from 5 templates (dashboard, subscribe, suspended, billing, billing_success) — base.html handles nav directly, these blocks were never rendered
  - Auth pages: "Welcome back" heading on login, "Create your account" (lowercase) on register, `btn-lg` on submit buttons, cleaner error state with SVG icon
  - Error pages: gradient error code numbers, contextual SVG icons (lock for 403, sad face for 404, warning for 500), better copy, proper `.btn-primary` styling
  - Portal dashboard: replaced `form-group` usage in website card with semantic `.site-info-item` classes
  - Ticket detail: uses `.back-link` component instead of inline styled link
  - Ticket new: uses `.back-link` component, removed `page-header-row` wrapper (simpler layout)
  - Billing page: uses `.back-link` component instead of bottom link
  - All headings use consistent sentence case (not Title Case)
- **app.js updated:**
  - Flash dismiss now includes `translateY(-4px)` animation for smoother exit
  - Added `copyInviteLink()` function directly in app.js (consolidates from inline scripts in admin templates)
- **Tests:** 152 total (25 auth + 9 portal + 12 billing + 10 webhooks + 32 tickets + 45 admin + 19 security), all passing

## What's Next: Phase 8 — Deployment (Railway)

## Domain Offer Policy

- **Included:** Free custom domain (up to $25/year) with an active subscription. We register and configure it.
- **Timeline:** Domain setup typically takes a few days after the client activates their subscription.
- **Over $25 (premium domains):** Client purchases the domain themselves at any registrar. We provide step-by-step DNS instructions (A record or CNAME). We only need the domain name from them — no registrar login required. Once they add the DNS records, we set `custom_domain` on the site and configure the host.
- **Client already owns a domain:** Same as above — we send DNS instructions, they point it, we connect it. No extra charge.
- **Copy used across all touchpoints:** "Free custom domain (up to $25/yr)" in feature lists. Fine print: "Standard domains (e.g. .com) up to $25/year included with your active subscription. Domain setup typically takes a few days after activation."
- **Touchpoints updated:** Landing page pricing, portal subscribe page, prospect outreach email, client invite email, subscription activated email, admin workspace convert form, admin workspace detail form.

## Key Design Decisions to Remember

1. **Invite-only signup** — no self-registration. Admin creates workspace + site + invite token, sends link.
2. **Subscription-based access gating** — `billing_subscriptions.status` is truth, `site.status` is derived/presentation.
3. **Idempotent webhooks** — `stripe_events` table deduplicates by `event_id`.
4. **Dual tenant isolation** — every portal query checks BOTH `workspace_id == g.workspace_id` AND membership exists.
5. **Dual Supabase connections** — pooler for runtime, direct for migrations.
6. **Prospects table (lite CRM)** — full pipeline: researching -> site_built -> pitched -> converted -> declined.
7. **Cloudflare is manual** — portal tracks URLs only. No API integration. Demo sites get `<meta name="robots" content="noindex">`.
8. **No templates/generators** — every client site is 100% custom-built by Chris.
9. **Cancellation = paused** — holding page deployed manually on Cloudflare. No buyout/export.
10. **Auth routes are slug-independent** — `/auth/login?next=...`, not `/auth/login/<slug>`.

## Gotchas / Notes for Future Sessions

- **Circular FK (prospects <-> workspaces):** Both tables have FKs pointing at each other. Models use `use_alter=True` with named constraints. The migration uses `batch_alter_table` to add these FKs after both tables are created. The two relationships (`Workspace.prospect` and `Prospect.workspace`) are NOT `back_populates` of each other — they are independent relationships using different FKs.
- **SQLite timezone issue:** `WorkspaceInvite.is_expired` property handles both naive (SQLite) and aware (Postgres) datetimes by adding UTC tzinfo to naive datetimes before comparison.
- `decorators.py` does a lazy import of `WorkspaceMember` — don't move or rename that model without updating the decorator.
- The `.env` file has SQLite for local dev. Switch to Supabase Postgres when Chris has his Supabase project set up.
- Flask-Login `user_loader` is in `extensions.py` (not in a separate file). It lazy-imports `User`.
- The webhook blueprint needs CSRF exemption — not implemented yet (Phase 4 task).
- `base.html` footer uses hardcoded '2026' (no Jinja `now()` global needed).
- **CSS is a full design system now** — 600+ lines, Stripe-inspired. Uses CSS custom properties for all colors/spacing. Has a full token system (gray-50 through gray-900, indigo, green, yellow, red, blue). Future phases should extend it, not rewrite. Key class patterns: `.stats-grid` > `.stat-card`, `.content-grid`, `.pricing-grid` > `.pricing-card`, `.cta-page`, `.subscription-card`, `.alert`, `.empty-state`, `.table-container` > `.table`.
- `Ticket.VALID_TRANSITIONS` dict is defined on the model class for service layer use.
- `AuditEvent.metadata_` is the Python attribute name (avoids clashing with Python's builtin), but the DB column is named `metadata`.
- `create_app()` imports models inside `with app.app_context()` using `from app import models` (NOT `import app.models` — that would shadow the `app` Flask instance variable).
- Alembic env.py has `render_as_batch=True` for SQLite compatibility and `DATABASE_DIRECT_URL` preference for migrations.
- **CSRF in templates:** Uses `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">` pattern (not WTForms' `form.hidden_tag()`). We don't use WTForms form classes — just plain HTML forms with the hidden CSRF input. `TestConfig` has `WTF_CSRF_ENABLED = False`.
- **invite_service.consume_invite() does NOT commit** — it only sets `used_at`. The caller (auth blueprint register route) commits as part of the larger transaction (user + membership + invite + audit).
- **invite_service.generate_invite() DOES commit** — it creates the invite and commits immediately. This is used by admin routes (Phase 6).
- **Test fixture DetachedInstanceError:** The `seed_data` fixture returns both SQLAlchemy objects AND plain string IDs (`workspace_id`, `site_id`, `admin_id`, `site_slug`). When accessing object attributes inside a different `app.app_context()` block in tests, use the plain string IDs to avoid DetachedInstanceError. Or re-query the object inside the new context.
- **TestConfig.SERVER_NAME = "localhost"** — required for `url_for()` to work in tests without a request context. If you get "Application was not able to create a URL adapter" errors, this is why.
- **Auth open redirect protection:** Login route only allows `next` URLs starting with `/`. External URLs are replaced with `/`.
- **Tenant middleware is registered BEFORE blueprints** in `create_app()`. It runs via `app.before_request()`. It only processes requests that have `site_slug` in `request.view_args` and skips `/static/`, `/auth/`, `/admin/`, `/stripe/` paths.
- **`g.access_level`** is computed by tenant middleware and available in all portal templates. Values: `"full"`, `"read_only"`, `"blocked"`, `"subscribe"`. Templates check this to conditionally render content.
- **Subscribe page** POSTs to `billing.checkout` with a `price_id` hidden field. Pricing cards use `config.STRIPE_BASIC_PRICE_ID` and `config.STRIPE_PRO_PRICE_ID`.
- **Dashboard "Manage billing" and "Update payment"** are now POST forms to `billing.customer_portal` (not GET links). They submit with CSRF token to create a Stripe Portal Session.
- **Suspended page "Resubscribe"** links to `billing.billing_overview` (GET) which renders subscribe.html when no active subscription exists.
- **`login_manager.login_view = "auth.login"`** — Flask-Login redirects unauthenticated users to this route automatically. The `next` query param is set by Flask-Login.
- **Webhook CSRF exemption** — `csrf.exempt(webhooks_bp)` is in `create_app()` after blueprint registration. Without this, Stripe webhooks would be rejected by Flask-WTF.
- **Stripe mocking in tests** — All Stripe API calls are mocked with `@patch("app.services.stripe_service.stripe")`. The mock targets the `stripe` module as imported in `stripe_service.py`, not the global `stripe` package.
- **ticket_service functions flush but don't commit** — `create_ticket`, `add_message`, `update_status`, `assign_ticket` all flush. The caller (portal blueprint) commits after the operation.
- **billing_service functions flush but don't commit** — `upsert_subscription`, `derive_site_status`, and `log_billing_audit` all call `db.session.flush()` not `commit()`. The caller (webhook handler's `handle_webhook_event`) commits after all operations succeed + after recording the StripeEvent.
- **get_or_create_billing_customer commits immediately** — unlike the other billing_service functions, this one commits because it needs the customer to be visible for the checkout session creation.
- **Billing blueprint route names**: `billing.checkout`, `billing.checkout_success`, `billing.checkout_cancel`, `billing.customer_portal`, `billing.billing_overview`. Templates reference these directly.
- **billing_success.html auto-redirects** after 5 seconds via inline `<script>` in the `{% block scripts %}` block. The assumption is the webhook will have processed by then.
- **Ticket auto-transition** — when a client (non-admin) replies to a ticket in `waiting_on_client` status, it automatically transitions to `in_progress`. Admin replies do NOT trigger this. Controlled in `ticket_service.add_message()`.
- **Ticket access gating** — ticket list (`GET /<slug>/tickets`) is accessible at all access levels (full, read_only, blocked) so clients can always VIEW existing tickets. But creating tickets and replying requires `g.access_level == "full"`. This means even blocked/canceled clients can browse their ticket history.
- **Portal route names for tickets**: `portal.ticket_list`, `portal.ticket_new`, `portal.ticket_detail`, `portal.ticket_reply`. Templates reference these directly.
- **`db.session.get()` over `Query.get()`** — ticket_service.py and portal.py use `db.session.get(Model, id)` instead of deprecated `Model.query.get(id)`. Eliminates SQLAlchemy 2.0 deprecation warnings.
- **Ticket workspace isolation** — detail and reply routes check `ticket.workspace_id != g.workspace_id` before rendering. If a client tries to access a ticket from another workspace, they get flashed "Ticket not found" and redirected to their ticket list.
- **Internal notes (is_internal)** — set on TicketMessage. `get_ticket_with_messages(include_internal=False)` filters them out for client view. Admin view passes `include_internal=True`. CSS class `.ticket-message-internal` (yellow background) is styled.
- **Admin blueprint route names**: `admin.dashboard`, `admin.prospect_list`, `admin.prospect_new`, `admin.prospect_detail`, `admin.prospect_update`, `admin.prospect_convert`, `admin.workspace_list`, `admin.workspace_detail`, `admin.workspace_invite`, `admin.ticket_list`, `admin.ticket_detail`, `admin.ticket_reply`, `admin.ticket_status`, `admin.ticket_assign`, `admin.site_status_override`. Templates reference these directly.
- **Flask-Limiter** — initialized in `extensions.py`, `init_app` called in `create_app()`. Uses `memory://` storage (in-process). For production with multiple workers, switch to Redis storage. Rate limits are applied as decorators on individual routes (`@limiter.limit()`), not globally. `RATELIMIT_ENABLED = False` in TestConfig.
- **Security headers** — added via `@app.after_request` in `create_app()`. CSP allows Stripe JS (`js.stripe.com`), Stripe API (`api.stripe.com`), Stripe checkout/billing form actions, and Stripe iframes. `unsafe-inline` is allowed for scripts (needed for billing_success.html auto-redirect) and styles (needed for inline SVG styles). HSTS is only set when `app.debug` is False (production).
- **Dead `nav_links` blocks** — several portal templates had `{% block nav_links %}` that was never defined in base.html. These were dead code and have been removed. The nav is fully handled by base.html using `current_user`, `g.site`, and `g.access_level` context.
- **venv** — created at `WaaS_Portal/venv/` using `python3 -m venv venv`. Activate with `source venv/bin/activate`. All dependencies installed including Flask-Limiter.
- **invite_service.generate_invite() commits immediately** — the prospect_convert route in admin.py calls this mid-transaction. Since it commits, the workspace/site/settings must be flushed before calling it. The rest of the conversion (prospect status update, audit log) commits separately after.
- **Prospect convert flow** — creates 4 records: Workspace, WorkspaceSettings, Site, WorkspaceInvite. Pre-fills from prospect record. Invite is generated via invite_service (which commits). Then prospect status is set to "converted" and workspace_id is linked. A final commit persists the prospect updates + audit.
- **Admin ticket controls** — status, assignment, and reply are separate POST routes. Status changes enforce the Ticket.VALID_TRANSITIONS state machine. Assignment validates the assignee is_admin.
- **Admin dashboard MRR** — calculated server-side by iterating active subscriptions and summing $59 (basic) or $99 (pro). This is a simple approach; for production scale, a proper query or cached value would be better.
- **copyInviteLink() JS function** — used in workspace_convert_success.html and workspace_invite_success.html. Uses navigator.clipboard.writeText() with fallback to input.select(). Changes button text to "Copied!" for 2 seconds.
- **Admin CSS badge colors** — pipeline statuses, sources, priorities, and plans all have dedicated badge color classes. These work with the existing `.badge` + `.badge-dot` pattern.

## File Quick Reference

| File | Purpose | Status |
|---|---|---|
| `app/__init__.py` | create_app factory + seed-admin CLI | Done |
| `app/config.py` | Config classes | Done |
| `app/extensions.py` | DB, migrate, login, CSRF | Done |
| `app/decorators.py` | @login_required_for_site, @admin_required | Done |
| `app/models/__init__.py` | Import all models for Alembic | Done |
| `app/models/user.py` | User model (8 cols, 5 relationships) | Done |
| `app/models/workspace.py` | Workspace + WorkspaceMember + WorkspaceSettings | Done |
| `app/models/prospect.py` | Prospects CRM (13 cols, pipeline statuses) | Done |
| `app/models/site.py` | Sites (9 cols, slug/url/status) | Done |
| `app/models/invite.py` | Workspace invites (token/expiry/validation) | Done |
| `app/models/billing.py` | BillingCustomer + BillingSubscription | Done |
| `app/models/stripe_event.py` | Stripe event idempotency | Done |
| `app/models/ticket.py` | Tickets + TicketMessages (status machine) | Done |
| `app/models/audit.py` | Audit events (action + metadata JSON) | Done |
| `migrations/env.py` | Alembic config (DATABASE_DIRECT_URL, batch mode) | Done |
| `migrations/versions/cd77260a1e5a_*.py` | Initial schema migration (13 tables) | Done |
| `app/blueprints/auth.py` | Auth routes (register/login/logout) | Done |
| `app/services/invite_service.py` | Invite token generate/validate/consume | Done |
| `app/templates/auth/login.html` | Login form template | Done |
| `app/templates/auth/register.html` | Register form template (invite-gated) | Done |
| `tests/conftest.py` | Test fixtures (app, db, client, seed_data) | Done |
| `tests/test_auth.py` | 25 auth tests (register, login, logout) | Done |
| `app/middleware/tenant.py` | Tenant resolution + access_level | Done |
| `app/blueprints/portal.py` | Portal routes (dashboard, root redirect) | Done |
| `app/templates/portal/dashboard.html` | Client dashboard (sub card, tickets, site info) | Done |
| `app/templates/portal/subscribe.html` | Pricing page (Basic/Pro cards) | Done |
| `app/templates/portal/suspended.html` | Subscription ended CTA page | Done |
| `tests/test_portal.py` | 9 portal tests (tenant, access levels, auth) | Done |
| `app/blueprints/billing.py` | Billing routes (checkout, portal, success, cancel, overview) | Done |
| `app/blueprints/admin.py` | Admin routes (16 routes: dashboard, prospects, workspaces, tickets, site override) | Done |
| `app/templates/admin/dashboard.html` | Admin dashboard (stats, pipeline, activity feed) | Done |
| `app/templates/admin/prospects.html` | Prospect pipeline list with filters | Done |
| `app/templates/admin/prospect_new.html` | Add new prospect form | Done |
| `app/templates/admin/prospect_detail.html` | Prospect detail (editable form + sidebar) | Done |
| `app/templates/admin/workspace_convert.html` | Convert prospect to client form | Done |
| `app/templates/admin/workspace_convert_success.html` | Conversion success + invite link | Done |
| `app/templates/admin/workspaces.html` | Workspace list table | Done |
| `app/templates/admin/workspace_detail.html` | Workspace detail (site, members, billing, invites, tickets) | Done |
| `app/templates/admin/workspace_invite_success.html` | New invite link display | Done |
| `app/templates/admin/tickets.html` | Cross-workspace ticket list with filters | Done |
| `app/templates/admin/ticket_detail.html` | Admin ticket detail (internal notes, controls) | Done |
| `tests/test_admin.py` | 45 admin tests (auth guards, dashboard, prospects, workspaces, tickets, site override) | Done |
| `app/blueprints/webhooks.py` | Stripe webhooks (signature verify, CSRF exempt, idempotent) | Done |
| `app/services/stripe_service.py` | Stripe API calls + webhook dispatch + 5 event handlers | Done |
| `app/services/billing_service.py` | DB sync helpers (upsert sub, derive site status, audit) | Done |
| `app/templates/portal/billing.html` | Billing overview (plan card, manage button) | Done |
| `app/templates/portal/billing_success.html` | Post-checkout success page with auto-redirect | Done |
| `tests/test_billing.py` | 12 billing tests (checkout, portal, overview, auth guards) | Done |
| `tests/test_webhooks.py` | 10 webhook tests (signature, idempotency, all 5 event types) | Done |
| `app/services/ticket_service.py` | Ticket CRUD, status machine, assignment, bleach sanitization | Done |
| `app/templates/portal/tickets/list.html` | Ticket list with status filter tabs | Done |
| `app/templates/portal/tickets/new.html` | Create ticket form (subject, category, description) | Done |
| `app/templates/portal/tickets/detail.html` | Ticket detail + message thread + reply form | Done |
| `tests/test_tickets.py` | 32 ticket tests (16 service + 16 route) | Done |
| `tests/test_security.py` | 19 security tests (headers, cross-tenant, rate limiting) | Done |
