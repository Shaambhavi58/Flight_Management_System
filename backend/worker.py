"""
worker.py — RabbitMQ Consumer for flight_create_queue.

Listens for flight creation requests published by POST /flights
and inserts them into the database via FlightService.

Batch Email Schedule (clock-based):
  - Morning   batch email → sent at 12:00 PM  (covers flights 00:00–11:59)
  - Afternoon batch email → sent at 06:00 PM  (covers flights 12:00–17:59)
  - Evening   batch email → sent at 11:59 PM  (covers flights 18:00–23:59)

Usage:
    python worker.py

Architecture:
    Frontend → POST /flights → RabbitMQ (flight_create_queue) → worker.py → DB
                                                                      ↓
                                                    Clock-based Batch Summary Email
"""

import pika
import json
import time
import os
import sys
import threading
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ── Settings ─────────────────────────────────────────────────────────────────
QUEUE_NAME    = "flight_create_queue"
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "guest")

MAX_RETRIES   = 10
PREFETCH      = 1

# ── Batch email schedule ──────────────────────────────────────────────────────
# Morning   flights (00:00–11:59) → email at 12:00 PM
# Afternoon flights (12:00–17:59) → email at 06:00 PM
# Evening   flights (18:00–23:59) → email at 11:59 PM
BATCH_SCHEDULE = [
    ("morning",   12,  0),
    ("afternoon", 18,  0),
    ("evening",   23, 59),
]


# ── BatchStore ────────────────────────────────────────────────────────────────

class BatchStore:
    """
    Thread-safe store that accumulates processed flights per batch_id.
    Flights are stored throughout the day.
    Emails are sent by the scheduler at fixed clock times.
    """

    def __init__(self):
        self._batches: dict = {
            "morning":   [],
            "afternoon": [],
            "evening":   [],
        }
        self._lock = threading.Lock()

    def record(self, batch_id: str, flight_info: dict):
        """Record a processed flight under its batch_id."""
        with self._lock:
            if batch_id not in self._batches:
                self._batches[batch_id] = []
            self._batches[batch_id].append(flight_info)
            count = len(self._batches[batch_id])
        print(f"[BatchStore] {batch_id.capitalize()} batch now has {count} flights.")

    def get_and_clear(self, batch_id: str) -> list:
        """Return all flights for a batch and clear the store."""
        with self._lock:
            flights = list(self._batches.get(batch_id, []))
            self._batches[batch_id] = []
        return flights


# ── Email Sender ──────────────────────────────────────────────────────────────

def _send_batch_email(batch_id: str, flights: list):
    """Send a batch summary email to BATCH_REPORT_EMAIL."""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    smtp_host     = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port     = int(os.getenv("SMTP_PORT", "587"))
    smtp_user     = os.getenv("SMTP_USER", "")
    smtp_password = os.getenv("SMTP_PASSWORD", "")
    report_email  = os.getenv("BATCH_REPORT_EMAIL", "")
    dashboard_url = os.getenv("DASHBOARD_URL", "http://127.0.0.1:8000")

    if not smtp_user or not smtp_password or not report_email:
        print("[BatchEmail] SMTP or BATCH_REPORT_EMAIL not configured. Skipping email.")
        return

    if not flights:
        print(f"[BatchEmail] No flights in {batch_id} batch. Skipping email.")
        return

    label = batch_id.capitalize()
    total = len(flights)

    time_ranges = {
        "morning":   "12:00 AM – 11:59 AM",
        "afternoon": "12:00 PM – 05:59 PM",
        "evening":   "06:00 PM – 11:59 PM",
    }
    time_range = time_ranges.get(batch_id, "")

    # ── Cap table at 30 rows ──────────────────────────────────────────────────
    MAX_ROWS  = 30
    displayed = flights[:MAX_ROWS]
    remaining = total - MAX_ROWS

    STATUS_COLORS = {
        "Scheduled": "#2196F3",
        "Boarding":  "#FF9800",
        "Departed":  "#4CAF50",
        "Arrived":   "#4CAF50",
        "Delayed":   "#F44336",
        "Cancelled": "#9E9E9E",
    }

    rows_html = ""
    for i, f in enumerate(displayed, 1):
        status_color = STATUS_COLORS.get(f.get("status", ""), "#333")
        row_bg = "#f9f9f9" if i % 2 == 0 else "white"
        rows_html += f"""
        <tr style="background:{row_bg};">
            <td style="padding:10px 14px; border-bottom:1px solid #eee;">{i}</td>
            <td style="padding:10px 14px; border-bottom:1px solid #eee; font-weight:600;
                       font-family:monospace; color:#0f3460;">
                {f.get('flight_number', '—')}
            </td>
            <td style="padding:10px 14px; border-bottom:1px solid #eee;">
                {f.get('airline_name', f.get('airline_code', '—'))}
            </td>
            <td style="padding:10px 14px; border-bottom:1px solid #eee; color:#444;">
                {f.get('origin', '—')} → {f.get('destination', '—')}
            </td>
            <td style="padding:10px 14px; border-bottom:1px solid #eee; text-align:center;">
                <span style="background:{status_color}; color:white; padding:3px 10px;
                             border-radius:12px; font-size:12px; font-weight:600;">
                    {f.get('status', '—')}
                </span>
            </td>
        </tr>
        """

    # ── Overflow link (only when flights > 30) ────────────────────────────────
    overflow_html = ""
    if remaining > 0:
        batch_link = f"{dashboard_url}?batch={batch_id}"
        overflow_html = f"""
        <div style="text-align:center; margin-top:16px;">
            <a href="{batch_link}"
               style="display:inline-block; padding:10px 24px;
                      background:#00a0d2; color:white; border-radius:8px;
                      text-decoration:none; font-size:14px; font-weight:600;">
                +{remaining} more flights processed — View Full Dashboard →
            </a>
        </div>
        """

    html_body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; background: #f5f5f5; padding: 30px;">
        <div style="max-width: 720px; margin: 0 auto; background: white;
                    border-radius: 12px; padding: 32px;
                    box-shadow: 0 2px 12px rgba(0,0,0,0.1);">

            <!-- Header -->
            <div style="text-align:center; margin-bottom:24px;">
                <h1 style="color:#00a0d2; margin:0; font-size:26px;">BEUMER Group</h1>
                <p style="color:#1a2b49; font-size:13px; margin-top:4px;">
                    Flight Management System — Batch Report
                </p>
            </div>

            <hr style="border:none; border-top:1px solid #e0e0e0; margin:16px 0;">

            <!-- Summary -->
            <h2 style="color:#1a2b49; margin-bottom:8px; font-size:20px;">
                {label} Batch — Flight Summary
            </h2>
            <table style="font-size:14px; color:#555; margin-bottom:20px; border-collapse:collapse;">
                <tr>
                    <td style="padding:4px 12px 4px 0;"><strong>Time slot</strong></td>
                    <td>{time_range}</td>
                </tr>
                <tr>
                    <td style="padding:4px 12px 4px 0;"><strong>Total flights</strong></td>
                    <td>{total}</td>
                </tr>
                <tr>
                    <td style="padding:4px 12px 4px 0;"><strong>Showing</strong></td>
                    <td>Top {min(total, MAX_ROWS)} flights</td>
                </tr>
            </table>

            <!-- Flight table -->
            <table style="width:100%; border-collapse:collapse; font-size:14px;">
                <thead>
                    <tr style="background:#1a2b49; color:white;">
                        <th style="padding:10px 14px; text-align:left;">#</th>
                        <th style="padding:10px 14px; text-align:left;">Flight No.</th>
                        <th style="padding:10px 14px; text-align:left;">Airline</th>
                        <th style="padding:10px 14px; text-align:left;">Route</th>
                        <th style="padding:10px 14px; text-align:center;">Status</th>
                    </tr>
                </thead>
                <tbody>{rows_html}</tbody>
            </table>

            {overflow_html}

            <hr style="border:none; border-top:1px solid #e0e0e0; margin:24px 0 16px;">
            <p style="color:#999; font-size:12px; text-align:center;">
                Beumer Group — Flight Management System &copy; 2026
            </p>
        </div>
    </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[FMS] {label} Batch Report — {total} Flights Processed"
    msg["From"]    = smtp_user
    msg["To"]      = report_email
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
        print(f"[BatchEmail] ✅ {label} summary sent to {report_email} "
              f"({total} total, {min(total, MAX_ROWS)} shown in email)")
    except Exception as e:
        print(f"[BatchEmail] ❌ Failed to send {label} email: {e}")




# ── Batch Email Scheduler ─────────────────────────────────────────────────────

class BatchEmailScheduler:
    """
    Runs in a background thread.
    Checks the clock every 30 seconds.
    Fires summary email at the scheduled time for each batch.
    """

    def __init__(self, batch_store: BatchStore):
        self._store = batch_store
        self._sent_today: set = set()
        self._last_checked_date = None

    def _reset_if_new_day(self):
        today = datetime.now().date()
        if self._last_checked_date != today:
            self._sent_today = set()
            self._last_checked_date = today
            print(f"[Scheduler] New day {today} — batch tracker reset.")

    def _check_and_send(self):
        now = datetime.now()
        self._reset_if_new_day()

        for batch_id, send_hour, send_minute in BATCH_SCHEDULE:
            if batch_id in self._sent_today:
                continue
            if now.hour == send_hour and now.minute >= send_minute:
                print(f"[Scheduler] ⏰ {now.strftime('%H:%M')} — Sending {batch_id} batch email...")
                flights = self._store.get_and_clear(batch_id)
                _send_batch_email(batch_id, flights)
                self._sent_today.add(batch_id)

    def run(self):
        print(f"[Scheduler] Started. Email schedule:")
        print(f"[Scheduler]   Morning   (12:00 AM–11:59 AM) → email at 12:00 PM")
        print(f"[Scheduler]   Afternoon (12:00 PM–05:59 PM) → email at 06:00 PM")
        print(f"[Scheduler]   Evening   (06:00 PM–11:59 PM) → email at 11:59 PM")
        while True:
            try:
                self._check_and_send()
            except Exception as e:
                print(f"[Scheduler] Error: {e}")
            time.sleep(30)


# ── FlightWorker ──────────────────────────────────────────────────────────────

class FlightWorker:

    def __init__(self):
        from services.service import FlightService
        self._service = FlightService()
        self._connection = None
        self._channel = None

        self._batch_store = BatchStore()
        self._scheduler   = BatchEmailScheduler(self._batch_store)

        t = threading.Thread(target=self._scheduler.run, daemon=True)
        t.start()

        print("[Worker] FlightWorker initialized.")

    def _connect(self):
        credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
        params = pika.ConnectionParameters(
            host=RABBITMQ_HOST,
            port=RABBITMQ_PORT,
            credentials=credentials,
            heartbeat=600,
            blocked_connection_timeout=300,
        )
        self._connection = pika.BlockingConnection(params)
        self._channel = self._connection.channel()
        self._channel.queue_declare(queue=QUEUE_NAME, durable=True)
        self._channel.basic_qos(prefetch_count=PREFETCH)
        print(f"[Worker] Connected to RabbitMQ at {RABBITMQ_HOST}:{RABBITMQ_PORT}")
        print(f"[Worker] Listening on queue: '{QUEUE_NAME}'")

    def _on_message(self, channel, method, properties, body):
        try:
            flight_data = json.loads(body)
            flight_number = flight_data.get("flight_number", "?")
            airport_id    = flight_data.get("airport_id", "?")
            batch_id      = flight_data.get("batch_id", "general")

            print(f"[Worker] Processing: flight={flight_number}  airport_id={airport_id}  batch={batch_id}")

            system_user = {
                "id": 0,
                "username": "system_worker",
                "role": "admin",
                "airport_id": None,
            }

            result = self._service.create_flight(flight_data, current_user=system_user)
            print(f"[Worker] Saved flight ID={result['id']}  "
                  f"number={result['flight_number']}  airport={result['airport_id']}")

            # Record in batch store for scheduled email
            if batch_id in ("morning", "afternoon", "evening"):
                self._batch_store.record(batch_id, {
                    "flight_number": result.get("flight_number"),
                    "airline_code":  result.get("airline_code"),
                    "airline_name":  result.get("airline_name"),
                    "origin":        result.get("origin"),
                    "destination":   result.get("destination"),
                    "status":        result.get("status"),
                })

            channel.basic_ack(delivery_tag=method.delivery_tag)

        except json.JSONDecodeError as e:
            print(f"[Worker] Invalid JSON message, dropping: {e}")
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

        except Exception as e:
            print(f"[Worker] Error processing flight: {e}")
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    def start(self):
        self._channel.basic_consume(
            queue=QUEUE_NAME,
            on_message_callback=self._on_message,
        )
        print(f"[Worker] Ready. Waiting for messages... (Ctrl+C to stop)")
        print("=" * 60)
        try:
            self._channel.start_consuming()
        except KeyboardInterrupt:
            print("\n[Worker] Shutting down gracefully...")
            self._channel.stop_consuming()
        finally:
            if self._connection and not self._connection.is_closed:
                self._connection.close()
            print("[Worker] Connection closed.")

    def run_with_retry(self):
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                print(f"[Worker] Connecting... (attempt {attempt}/{MAX_RETRIES})")
                self._connect()
                self.start()
                break
            except pika.exceptions.AMQPConnectionError:
                wait = min(attempt * 3, 30)
                print(f"[Worker] RabbitMQ not available. Retrying in {wait}s...")
                time.sleep(wait)
            except KeyboardInterrupt:
                print("\n[Worker] Interrupted. Exiting.")
                sys.exit(0)
            except Exception as e:
                print(f"[Worker] Unexpected error: {e}. Retrying in 5s...")
                time.sleep(5)
        else:
            print(f"[Worker] Failed to connect after {MAX_RETRIES} attempts. Exiting.")
            sys.exit(1)


# ──Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  Beumer Group Flight Management System — Flight Create Worker")
    print(f"  Queue : {QUEUE_NAME}")
    print(f"  Broker: {RABBITMQ_HOST}:{RABBITMQ_PORT}")
    print("=" * 60)

    worker = FlightWorker()
    worker.run_with_retry()