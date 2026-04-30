"""
EmailService — Sends credential emails via Gmail SMTP.
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()


class EmailService:
    """
    Handles sending emails via SMTP (Gmail).
    Reads configuration from environment variables.
    """

    def __init__(self):
        self._host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        self._port = int(os.getenv("SMTP_PORT", "587"))
        self._user = os.getenv("SMTP_USER", "")
        self._password = os.getenv("SMTP_PASSWORD", "")

    def send_credentials_email(
        self, to_email: str, full_name: str, username: str, password: str, role: str
    ) -> bool:
        """
        Send login credentials to a newly registered user.
        Returns True on success, False on failure.
        """
        if not self._user or not self._password:
            print("[Email] SMTP not configured. Skipping email.")
            return False

        subject = "Your Flight Management System Login Credentials"
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

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self._user
        msg["To"] = to_email
        msg.attach(MIMEText(html_body, "html"))

        try:
            with smtplib.SMTP(self._host, self._port) as server:
                server.starttls()
                server.login(self._user, self._password)
                server.send_message(msg)
            print(f"[Email] Credentials sent to {to_email}")
            return True
        except Exception as e:
            print(f"[Email] Failed to send email to {to_email}: {e}")
            return False
