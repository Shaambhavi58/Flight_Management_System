"""
config.py — Centralized Configuration Module
=============================================
Reads all environment variables from .env via python-dotenv.
All other modules import from `settings` so secrets never appear in code.
"""

import os
from dotenv import load_dotenv

# Load .env file into the process environment before reading any variables
load_dotenv()


class Settings:
    """
    Central settings object. All values come from .env.
    Fallback defaults are safe for local development only —
    never use default secrets in production.
    """

    # ── MySQL connection details ─────────────────────────────────────────────
    MYSQL_HOST     = os.getenv("MYSQL_HOST", "localhost")    # DB server hostname or IP
    MYSQL_PORT     = os.getenv("MYSQL_PORT", "3306")         # MySQL listens on 3306 by default
    MYSQL_USER     = os.getenv("MYSQL_USER", "root")         # DB username
    MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")         # DB password — NEVER hardcode this
    MYSQL_DB       = os.getenv("MYSQL_DB", "flight_management")  # Target database name

    # ── SMTP email configuration (Gmail) ─────────────────────────────────────
    SMTP_HOST     = os.getenv("SMTP_HOST", "smtp.gmail.com")  # Gmail SMTP server
    SMTP_PORT     = int(os.getenv("SMTP_PORT", "587"))         # 587 = STARTTLS port
    SMTP_USER     = os.getenv("SMTP_USER", "")                 # Gmail address used to send
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")             # Gmail App Password (not account password)

    # ── JWT authentication settings ──────────────────────────────────────────
    JWT_SECRET      = os.getenv("JWT_SECRET", "flight-mgmt-secret-key-2026")  # Signing key for tokens
    JWT_ALGORITHM   = os.getenv("JWT_ALGORITHM", "HS256")                      # HMAC-SHA256 algorithm
    JWT_EXPIRY_HOURS = int(os.getenv("JWT_EXPIRY_HOURS", "24"))                # Token lifetime in hours

    # ── External API keys ────────────────────────────────────────────────────
    AVIATIONSTACK_KEY = os.getenv("AVIATIONSTACK_KEY", "")  # AviationStack API key (optional)
    RABBITMQ_HOST     = os.getenv("RABBITMQ_HOST", "localhost")  # RabbitMQ broker address

    # ── OpenSky Network credentials (live flight status) ────────────────────
    OPENSKY_USERNAME = os.getenv("OPENSKY_USERNAME", "")  # OpenSky account username
    OPENSKY_PASSWORD = os.getenv("OPENSKY_PASSWORD", "")  # OpenSky account password


# Module-level singleton — import this instance everywhere instead of
# instantiating Settings() multiple times
settings = Settings()
