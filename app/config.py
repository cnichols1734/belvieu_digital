import os


class Config:
    """Base configuration. Shared across all environments."""

    # --- Required ---
    SECRET_KEY = os.environ.get("SECRET_KEY")

    # Handle DATABASE_URL: some PaaS providers (Railway, Heroku) use
    # "postgres://" which SQLAlchemy 1.4+ doesn't accept.
    _db_url = os.environ.get("DATABASE_URL", "")
    if _db_url.startswith("postgres://"):
        _db_url = _db_url.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_DATABASE_URI = _db_url or None

    STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
    STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")
    STRIPE_BASIC_PRICE_ID = os.environ.get("STRIPE_BASIC_PRICE_ID")
    STRIPE_SETUP_PRICE_ID = os.environ.get("STRIPE_SETUP_PRICE_ID")
    STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY")
    APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:5000")

    # --- Promo pricing ---
    # When True, the $250 setup fee is waived site-wide (Stripe, UI, emails).
    PROMO_NO_SETUP_FEE = os.environ.get(
        "PROMO_NO_SETUP_FEE", ""
    ).lower() in ("1", "true", "yes")

    # --- Email (Google Workspace SMTP) ---
    MAIL_SMTP_HOST = os.environ.get("MAIL_SMTP_HOST", "smtp.gmail.com")
    MAIL_SMTP_PORT = int(os.environ.get("MAIL_SMTP_PORT", 587))
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")          # e.g. info@belvieudigital.com
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")          # Google App Password
    MAIL_FROM_NAME = os.environ.get("MAIL_FROM_NAME", "Belvieu Digital")
    MAIL_FROM_ADDRESS = os.environ.get("MAIL_FROM_ADDRESS")  # defaults to MAIL_USERNAME
    MAIL_CONTACT_TO = os.environ.get("MAIL_CONTACT_TO", "info@belvieudigital.com")

    # --- Domain search ---
    DOMAIN_PRICE_LIMIT = float(os.environ.get("DOMAIN_PRICE_LIMIT", 25.00))

    # --- Supabase ---
    # Pooler URL for runtime, direct URL for migrations (DDL).
    DATABASE_DIRECT_URL = os.environ.get("DATABASE_DIRECT_URL")
    SUPABASE_URL = os.environ.get("SUPABASE_URL")                # e.g. https://xyz.supabase.co
    SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY") # service_role key for storage
    SUPABASE_STORAGE_BUCKET = os.environ.get("SUPABASE_STORAGE_BUCKET", "ticket-attachments")

    # --- SQLAlchemy ---
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }

    # --- Session / cookies ---
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"

    # --- WTF / CSRF ---
    WTF_CSRF_ENABLED = True

    @staticmethod
    def validate():
        """Fail fast if required env vars are missing."""
        required = [
            "SECRET_KEY",
            "DATABASE_URL",
            "STRIPE_SECRET_KEY",
            "STRIPE_WEBHOOK_SECRET",
            "STRIPE_BASIC_PRICE_ID",
            "APP_BASE_URL",
        ]
        # Setup price ID is only required when promo is OFF
        promo_on = os.environ.get(
            "PROMO_NO_SETUP_FEE", ""
        ).lower() in ("1", "true", "yes")
        if not promo_on:
            required.append("STRIPE_SETUP_PRICE_ID")
        missing = [v for v in required if not os.environ.get(v)]
        if missing:
            raise RuntimeError(
                f"Missing required environment variables: {', '.join(missing)}"
            )


class DevConfig(Config):
    """Local development."""

    DEBUG = True
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False


class TestConfig(Config):
    """Testing — in-memory SQLite, CSRF disabled."""

    TESTING = True
    DEBUG = True
    SECRET_KEY = "test-secret-key-not-for-production"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    STRIPE_SECRET_KEY = "sk_test_fake"
    STRIPE_WEBHOOK_SECRET = "whsec_test_fake"
    STRIPE_BASIC_PRICE_ID = "price_basic_test"
    STRIPE_SETUP_PRICE_ID = "price_setup_test"
    STRIPE_PUBLISHABLE_KEY = "pk_test_fake"
    APP_BASE_URL = "http://localhost:5000"
    PROMO_NO_SETUP_FEE = False  # default off in tests; override per-test as needed
    WTF_CSRF_ENABLED = False  # disable CSRF for test forms
    RATELIMIT_ENABLED = False  # disable rate limiting in tests
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False
    SERVER_NAME = "localhost"

    @staticmethod
    def validate():
        """Skip validation in test mode — everything is hardcoded."""
        pass


class ProdConfig(Config):
    """Production on Railway."""

    DEBUG = False
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True


config_by_name = {
    "development": DevConfig,
    "production": ProdConfig,
    "testing": TestConfig,
}
