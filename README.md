# WaaS Portal

Client portal and admin dashboard for a Website-as-a-Service business.

**Stack:** Flask, Supabase (Postgres), Stripe, Railway

## Local Development

```bash
# 1. Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy env template and fill in values
cp .env.example .env
# Edit .env with your Supabase, Stripe, and secret values

# 4. Run database migrations
flask db upgrade

# 5. Seed admin user
flask seed-admin

# 6. Start the dev server
python run.py
```

## Environment Variables

See `.env.example` for the full list. Key variables:

| Variable | Description |
|---|---|
| `SECRET_KEY` | Flask secret key (min 32 random bytes) |
| `DATABASE_URL` | Supabase pooler connection string |
| `DATABASE_DIRECT_URL` | Supabase direct connection (for migrations) |
| `STRIPE_SECRET_KEY` | Stripe API secret key |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook signing secret |
| `STRIPE_BASIC_PRICE_ID` | Stripe Price ID for Basic plan ($59/mo) |
| `STRIPE_PRO_PRICE_ID` | Stripe Price ID for Pro plan ($99/mo) |
| `APP_BASE_URL` | Base URL of the app (e.g. `https://portal.yourdomain.com`) |

## Deployment (Railway)

1. Push repo to GitHub
2. Connect Railway to the repo
3. Set all environment variables in Railway dashboard
4. Run `flask db upgrade` via Railway CLI
5. Run `flask seed-admin` to create admin user
6. Configure Stripe webhook to `https://portal.yourdomain.com/stripe/webhooks`
7. Configure custom domain in Railway

## Stripe Webhook (Local Testing)

```bash
stripe listen --forward-to localhost:5000/stripe/webhooks
```
