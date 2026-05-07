import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def send_test_email():
    """
    Sends a sample batch summary email to verify SMTP configuration.
    """
    smtp_host     = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port     = int(os.getenv("SMTP_PORT", "587"))
    smtp_user     = os.getenv("SMTP_USER", "")
    smtp_password = os.getenv("SMTP_PASSWORD", "")
    report_email  = os.getenv("BATCH_REPORT_EMAIL", "")

    if not smtp_user or not smtp_password or not report_email:
        print("[Test Email] ERROR: SMTP_USER, SMTP_PASSWORD, or BATCH_REPORT_EMAIL not found in .env")
        return

    print(f"[Test Email] Preparing to send test email to {report_email}...")

    subject = "Beumer FMS Test Batch Email"
    body = """
    <html>
    <body style="font-family: Arial, sans-serif; background: #f5f5f5; padding: 20px;">
        <div style="max-width: 600px; margin: 0 auto; background: white; border-radius: 8px; padding: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
            <h1 style="color: #00a0d2;">Beumer Group FMS</h1>
            <p style="color: #333; font-size: 16px;">
                This is a <strong>test batch summary email</strong> from the Beumer Flight Management System.
            </p>
            <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
            <p style="color: #666; font-size: 14px;">
                If you received this email, your SMTP configuration is correct and the worker is ready to send automated reports.
            </p>
            <p style="color: #999; font-size: 12px; text-align: center; margin-top: 20px;">
                Beumer Group — Flight Management System &copy; 2026
            </p>
        </div>
    </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = smtp_user
    msg["To"]      = report_email
    msg.attach(MIMEText(body, "html"))

    try:
        print(f"[Test Email] Connecting to {smtp_host}:{smtp_port}...")
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
        print(f"[Test Email] SUCCESS! Please check your inbox: {report_email}")
    except Exception as e:
        print(f"[Test Email] FAILED: {e}")

if __name__ == "__main__":
    send_test_email()
