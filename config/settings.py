"""Django settings for PriceWatch.

Everything that differs between environments comes from environment variables
or a local `.env` file (see `.env.example`).
"""

from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
if (BASE_DIR / ".env").is_file():
    env.read_env(BASE_DIR / ".env")

# --- Core ---------------------------------------------------------------------

DEBUG = env.bool("DJANGO_DEBUG", default=False)
# The "django-insecure-" prefix makes `manage.py check --deploy` flag this fallback key.
SECRET_KEY = env("DJANGO_SECRET_KEY", default="django-insecure-local-development-only")
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "rest_framework",
    "rest_framework.authtoken",
    "django_filters",
    "drf_spectacular",
    "apps.catalog",
    "apps.bot",
    "apps.dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --- Database -------------------------------------------------------------------
# PostgreSQL through DATABASE_URL (postgres://user:password@host:5432/name),
# SQLite in the project folder when it is not set.

if env("DATABASE_URL", default=""):
    DATABASES = {"default": env.db("DATABASE_URL")}
else:
    DATABASES = {
        "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}
    }
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Localization and static files ------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Europe/Kyiv"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# Hashed file names need `collectstatic` first, so they are switched on in the Docker image.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        if env.bool("DJANGO_STATIC_MANIFEST", default=False)
        else "whitenoise.storage.CompressedStaticFilesStorage"
    },
}

LOGIN_URL = "admin:login"

# --- Production security ------------------------------------------------------------
# Behind a TLS-terminating proxy (nginx, Caddy, a PaaS) set DJANGO_HTTPS=true.

if env.bool("DJANGO_HTTPS", default=False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = env.int("DJANGO_HSTS_SECONDS", default=60 * 60 * 24 * 30)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = False
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# --- REST API -------------------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["apps.api.permissions.IsStaffOrReadOnly"],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": env("API_ANON_RATE", default="60/min"),
        "user": env("API_USER_RATE", default="600/min"),
    },
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "PriceWatch API",
    "DESCRIPTION": "Tracked products, their price history and on-demand price checks.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# --- Logging --------------------------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "{asctime} {levelname} {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
}

# --- Celery ---------------------------------------------------------------------

REDIS_URL = env("REDIS_URL", default="redis://127.0.0.1:6379/0")
CELERY_BROKER_URL = REDIS_URL
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_TASK_IGNORE_RESULT = True
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_SOFT_TIME_LIMIT = 90
CELERY_TASK_TIME_LIMIT = 120
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULE = {
    "enqueue-due-price-checks": {
        "task": "catalog.enqueue_due_checks",
        "schedule": timedelta(minutes=env.int("PRICE_CHECK_TICK_MINUTES", default=5)),
    },
}

# --- PriceWatch -----------------------------------------------------------------

# How often each product is re-checked, and how many checks one scheduler tick may queue.
PRICE_CHECK_INTERVAL = timedelta(minutes=env.int("PRICE_CHECK_INTERVAL_MINUTES", default=60))
PRICE_CHECK_BATCH_SIZE = env.int("PRICE_CHECK_BATCH_SIZE", default=200)

# Empty user agent means scraping.fetchers.DEFAULT_USER_AGENT.
SCRAPER_USER_AGENT = env("SCRAPER_USER_AGENT", default="")
SCRAPER_TIMEOUT = env.float("SCRAPER_TIMEOUT_SECONDS", default=20.0)
SCRAPER_RESPECT_ROBOTS_TXT = env.bool("SCRAPER_RESPECT_ROBOTS_TXT", default=True)
# Pause between requests in `manage.py check_prices`, and the Celery rate limit per worker.
SCRAPER_DELAY = env.float("SCRAPER_DELAY_SECONDS", default=2.0)
SCRAPER_RATE_LIMIT = env("SCRAPER_RATE_LIMIT", default="30/m")

# Headless browser for listings that grow through a JavaScript "load more" button.
# PLAYWRIGHT_CHANNEL=chrome uses the installed Google Chrome instead of `playwright install`.
PLAYWRIGHT_CHANNEL = env("PLAYWRIGHT_CHANNEL", default="")
PLAYWRIGHT_TIMEOUT = env.float("PLAYWRIGHT_TIMEOUT_SECONDS", default=30.0)

# --- Telegram bot ---------------------------------------------------------------

TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN", default="")
BOT_MAX_SUBSCRIPTIONS = env.int("BOT_MAX_SUBSCRIPTIONS", default=50)

# --- Dashboard ------------------------------------------------------------------

# Public by default so a demo can be shown without an account.
DASHBOARD_LOGIN_REQUIRED = env.bool("DASHBOARD_LOGIN_REQUIRED", default=False)
