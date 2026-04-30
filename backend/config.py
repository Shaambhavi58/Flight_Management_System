"""
Centralized Configuration Module
"""
import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
    MYSQL_PORT = os.getenv("MYSQL_PORT", "3306")
    MYSQL_USER = os.getenv("MYSQL_USER", "root")
    MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
    MYSQL_DB = os.getenv("MYSQL_DB", "flight_management")

    SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")

    JWT_SECRET = os.getenv("JWT_SECRET", "flight-mgmt-secret-key-2026")
    JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
    JWT_EXPIRY_HOURS = int(os.getenv("JWT_EXPIRY_HOURS", "24"))

    AVIATIONSTACK_KEY = os.getenv("AVIATIONSTACK_KEY", "")
    RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")

    OPENSKY_USERNAME = os.getenv("OPENSKY_USERNAME", "")
    OPENSKY_PASSWORD = os.getenv("OPENSKY_PASSWORD", "")

settings = Settings()
