"""
services/email_service.py
==========================
EmailService — Sends HTML emails via Gmail SMTP (STARTTLS).

Methods:
  send_credentials_email()            — welcome email for new users (contains password)
  send_password_change_notification() — security alert to admin when a staff user
                                        changes their own password (NO password included)

SMTP configuration is loaded exclusively from environment variables.

Required .env keys:
  SMTP_HOST          (default: smtp.gmail.com)
  SMTP_PORT          (default: 587 — STARTTLS)
  SMTP_USER          Gmail address used as sender
  SMTP_PASSWORD      Gmail App Password
  ADMIN_ALERT_EMAIL  Where password-change notifications are sent
                     (falls back to SMTP_USER if not set)
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
        # Read SMTP settings from .env
        self._host     = os.getenv("SMTP_HOST", "smtp.gmail.com")
        self._port     = int(os.getenv("SMTP_PORT", "587"))
        self._user     = os.getenv("SMTP_USER", "")
        self._password = os.getenv("SMTP_PASSWORD", "")
        # Admin alert destination — falls back to the sender address itself
        self._admin_email = os.getenv("ADMIN_ALERT_EMAIL") or os.getenv("SMTP_USER", "")

    # ── Internal SMTP helper ──────────────────────────────────────────────────

    def _send(self, to_email: str, subject: str, html_body: str) -> bool:
        """
        Low-level SMTP delivery helper shared by all send_* methods.
        Opens a STARTTLS connection, authenticates, sends, and closes cleanly.

        Returns True on success, False on any failure (SMTP error, bad credentials, etc.).
        Email failures are logged but never re-raised so callers are never blocked.
        """
        if not self._user or not self._password:
            print("[Email] SMTP not configured — skipping.")
            return False

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = self._user
        msg["To"]      = to_email
        msg.attach(MIMEText(html_body, "html"))

        try:
            with smtplib.SMTP(self._host, self._port) as server:
                server.starttls()
                server.login(self._user, self._password)
                server.send_message(msg)
            print(f"[Email] '{subject}' sent to {to_email}")
            return True
        except Exception as e:
            print(f"[Email] Failed to send '{subject}' to {to_email}: {e}")
            return False

    def send_notification(self, to_email: str, subject: str, body: str) -> bool:
        """
        Public method to send a simple HTML notification email.
        Converts newline characters in `body` to <br> tags.
        """
        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h2 style="color: #1a2b49;">System Notification</h2>
            <p style="white-space: pre-line;">{body}</p>
            <hr style="border: 0; border-top: 1px solid #eee; margin: 20px 0;">
            <p style="font-size: 12px; color: #777;">Beumer Group — Flight Management System Security</p>
        </body>
        </html>
        """
        return self._send(to_email, subject, html_body)

    # ── Public methods ────────────────────────────────────────────────────────

    def send_credentials_email(
        self, to_email: str, full_name: str, username: str, password: str, role: str
    ) -> bool:
        """
        Send a welcome email containing the new user's login credentials.
        The plaintext password is shown exactly once — in this email only.

        Args:
            to_email:  Recipient's email address
            full_name: Used in the greeting
            username:  Login username
            password:  Plaintext password (shown once, never stored in plain)
            role:      User role (admin / staff / viewer)

        Returns:
            True on delivery, False if SMTP is unconfigured or fails.
        """
        subject   = "Your Flight Management System Login Credentials"
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
                    <p style="margin: 4px 0; color: #333;"><strong>Username:</strong> {username}</p>
                    <p style="margin: 4px 0; color: #333;"><strong>Password:</strong> {password}</p>
                    <p style="margin: 4px 0; color: #333;"><strong>Role:</strong> {role.capitalize()}</p>
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
        return self._send(to_email, subject, html_body)

    def send_password_change_notification(
        self,
        full_name: str,
        username: str,
        role: str,
        airport_name: str,
        changed_at: str,
    ) -> bool:
        """
        Send a security-alert email to the configured admin address whenever
        a staff or viewer user changes their own password.

        The new password is NEVER included — only audit metadata:
          full_name, username, role, assigned airport, and UTC timestamp.

        If admin needs to intervene, they should use the Admin → Reset Password
        flow in the management UI (which requires a fresh password, not the old one).

        Args:
            full_name:    Display name of the user
            username:     Login username
            role:         User role (staff / viewer)
            airport_name: Name of the assigned airport
            changed_at:   UTC timestamp string (ISO 8601)

        Returns:
            True on delivery, False if SMTP is unconfigured or fails.
        """
        to_email = self._admin_email
        if not to_email:
            print("[Email] No admin email configured — skipping password-change notification.")
            return False

        subject   = f"[FMS Security Alert] Password Changed — {username}"
        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; background: #f5f5f5; padding: 30px;">
            <div style="max-width: 520px; margin: 0 auto; background: white; border-radius: 12px;
                        padding: 32px; box-shadow: 0 2px 12px rgba(0,0,0,0.1);">

                <!-- Header -->
                <div style="text-align: center; margin-bottom: 20px;">
                    <h1 style="color: #00a0d2; margin: 0;">BEUMER Group</h1>
                    <p style="color: #1a2b49; font-size: 14px; margin-top: 4px;">
                        Flight Management System &mdash; Security Notification
                    </p>
                </div>
                <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 16px 0;">

                <!-- Alert banner -->
                <div style="background: #fff7ed; border-left: 4px solid #f59e0b;
                            padding: 14px 16px; border-radius: 6px; margin-bottom: 20px;">
                    <p style="margin: 0; color: #92400e; font-weight: 600; font-size: 15px;">
                        &#9888; Password Change Detected
                    </p>
                    <p style="margin: 6px 0 0; color: #78350f; font-size: 13px;">
                        A user has changed their own password. No action is required
                        unless this change was unexpected.
                    </p>
                </div>

                <!-- Details table -->
                <p style="color: #333; font-size: 14px; margin-bottom: 12px;">
                    <strong>Change details:</strong>
                </p>
                <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                    <tr style="background: #f8fafc;">
                        <td style="padding: 10px 14px; color: #64748b; font-weight: 600;
                                   border-bottom: 1px solid #e2e8f0; width: 40%;">Full Name</td>
                        <td style="padding: 10px 14px; color: #1a2b49;
                                   border-bottom: 1px solid #e2e8f0;">{full_name}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px 14px; color: #64748b; font-weight: 600;
                                   border-bottom: 1px solid #e2e8f0;">Username</td>
                        <td style="padding: 10px 14px; color: #1a2b49; font-family: monospace;
                                   border-bottom: 1px solid #e2e8f0;">{username}</td>
                    </tr>
                    <tr style="background: #f8fafc;">
                        <td style="padding: 10px 14px; color: #64748b; font-weight: 600;
                                   border-bottom: 1px solid #e2e8f0;">Role</td>
                        <td style="padding: 10px 14px; color: #1a2b49;
                                   border-bottom: 1px solid #e2e8f0;">{role.capitalize()}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px 14px; color: #64748b; font-weight: 600;
                                   border-bottom: 1px solid #e2e8f0;">Assigned Airport</td>
                        <td style="padding: 10px 14px; color: #1a2b49;
                                   border-bottom: 1px solid #e2e8f0;">{airport_name}</td>
                    </tr>
                    <tr style="background: #f8fafc;">
                        <td style="padding: 10px 14px; color: #64748b; font-weight: 600;">
                            Changed At (UTC)</td>
                        <td style="padding: 10px 14px; color: #1a2b49;
                                   font-family: monospace;">{changed_at}</td>
                    </tr>
                </table>

                <!-- Security note -->
                <div style="background: #f0fdf4; border-left: 4px solid #10b981;
                            padding: 12px 16px; border-radius: 6px; margin-top: 20px;">
                    <p style="margin: 0; color: #065f46; font-size: 12px;">
                        &#128274; The new password is <strong>not</strong> included in this
                        notification and is stored only as a bcrypt hash in the database.
                        If you need to reset this user&apos;s password, use the
                        Admin &rarr; Reset Password flow in the management UI.
                    </p>
                </div>

                <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 20px 0;">
                <p style="color: #999; font-size: 12px; text-align: center;">
                    Beumer Group - Flight Management System &copy; 2026
                </p>
            </div>
        </body>
        </html>
        """
        return self._send(to_email, subject, html_body)
