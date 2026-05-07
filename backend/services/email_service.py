"""
services/email_service.py
==========================
EmailService — Sends HTML credential emails via Gmail SMTP (STARTTLS).

Called by AuthService.register_user() immediately after a new user is
created in the DB to deliver their login credentials by email.

SMTP configuration is loaded exclusively from environment variables —
never hardcode host/port/credentials in source code.

Required .env keys:
  SMTP_HOST     (default: smtp.gmail.com)
  SMTP_PORT     (default: 587 — STARTTLS)
  SMTP_USER     Gmail address used as the sender
  SMTP_PASSWORD Gmail App Password (NOT your Google account password)
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()


class EmailService:
    """
    Sends HTML-formatted emails through Gmail's SMTP server using STARTTLS.
    Configuration is loaded from environment variables — safe for production.
    """

    def __init__(self):
        # Read SMTP settings from .env (loaded by load_dotenv() above)
        self._host     = os.getenv("SMTP_HOST", "smtp.gmail.com")  # Gmail SMTP endpoint
        self._port     = int(os.getenv("SMTP_PORT", "587"))         # 587 = STARTTLS (not SSL)
        self._user     = os.getenv("SMTP_USER", "")                 # Sender Gmail address
        self._password = os.getenv("SMTP_PASSWORD", "")             # Gmail App Password

    def send_credentials_email(
        self, to_email: str, full_name: str, username: str, password: str, role: str
    ) -> bool:
        """
        Compose and send a styled HTML email containing the new user's login credentials.

        Args:
            to_email:  Recipient's email address
            full_name: Used in the greeting line of the email
            username:  Login username to display
            password:  Plaintext password — shown ONCE in the welcome email only
            role:      User role (admin / staff / viewer) shown in the email

        Returns:
            True on successful delivery, False if SMTP is unconfigured or fails.
        """
        # Guard: if SMTP credentials are not set in .env, skip silently
        # This allows the app to run in local dev without email configuration
        if not self._user or not self._password:
            print("[Email] SMTP not configured. Skipping email.")
            return False

        subject = "Your Flight Management System Login Credentials"

        # Build the HTML email body — inline styles are used for maximum email client compatibility
        # (many email clients strip external CSS)
        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; background: #f5f5f5; padding: 30px;">
            <div style="max-width: 500px; margin: 0 auto; background: white; border-radius: 12px;
                        padding: 32px; box-shadow: 0 2px 12px rgba(0,0,0,0.1);">
                <div style="text-align: center; margin-bottom: 24px;">
                    <h1 style="color: #00a0d2; margin: 0;">BEUMER Group</h1>
                    <p style="color: #1a2b49; font-size: 14px; margin-top: 4px;">
                        Flight Management System
                    </p>
                </div>
                <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 16px 0;">
                <p style="color: #333;">Hello <strong>{full_name}</strong>,</p>
                <p style="color: #555;">
                    Your account has been created on the Flight Management System.
                    Here are your login credentials:
                </p>
                <!-- Credentials card — highlighted box for easy readability -->
                <div style="background: #f0f9ff; border-left: 4px solid #00a0d2;
                            padding: 16px; border-radius: 6px; margin: 20px 0;">
                    <p style="margin: 4px 0; color: #333;">
                        <strong>Username:</strong> {username}
                    </p>
                    <p style="margin: 4px 0; color: #333;">
                        <strong>Password:</strong> {password}
                    </p>
                    <p style="margin: 4px 0; color: #333;">
                        <strong>Role:</strong> {role.capitalize()}
                    </p>
                </div>
                <p style="color: #555; font-size: 13px;">
                    Please change your password after your first login.
                </p>
                <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 16px 0;">
                <p style="color: #999; font-size: 12px; text-align: center;">
                    Beumer Group - Flight Management System &copy; 2026
                </p>
            </div>
        </body>
        </html>
        """

        # Compose the MIME message with HTML content type
        msg = MIMEMultipart("alternative")  # "alternative" allows fallback to plaintext
        msg["Subject"] = subject
        msg["From"]    = self._user         # sender displayed in recipient's inbox
        msg["To"]      = to_email
        msg.attach(MIMEText(html_body, "html"))  # attach HTML part

        try:
            # Open SMTP connection, upgrade to TLS, authenticate, and send
            with smtplib.SMTP(self._host, self._port) as server:
                server.starttls()                        # upgrade plain TCP to TLS
                server.login(self._user, self._password) # authenticate with Gmail
                server.send_message(msg)                 # deliver the email

            print(f"[Email] Credentials sent to {to_email}")
            return True

        except Exception as e:
            # Log the failure but do NOT raise — email failure should not block registration
            print(f"[Email] Failed to send email to {to_email}: {e}")
            return False
