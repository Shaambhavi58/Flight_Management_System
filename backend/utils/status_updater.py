"""
utils/status_updater.py
========================
Background asyncio task that recomputes and updates flight statuses every 60 seconds.

Status priority (applied in order):
  1. Cancelled  → never overridden
  2. Arrived    → flight has landed (now > arrival time)
  3. Departed   → airborne (now > departure but not yet arrived)
  4. Boarding   → within 5 minutes of departure
  5. Delayed    → random chance within 45-minute pre-departure window
  6. Scheduled  → default for future flights
"""

import asyncio    # for the non-blocking async sleep loop inside FastAPI
import random     # for realistic probabilistic Delayed status simulation
from datetime import datetime, timedelta
from core.database import DatabaseManager  # singleton DB engine and session scope
from models.models import FlightModel      # SQLAlchemy ORM model for the flights table


class StatusUpdater:
    """
    Computes and applies realistic flight status updates.
    Called by the async status_update_loop every 60 seconds.
    """

    @staticmethod
    def compute_status(dep_time: str, arr_time: str, current_status: str) -> str:
        """
        Determine the correct status for a flight based on current wall-clock time.

        Args:
            dep_time:       "HH:MM" string — scheduled departure time
            arr_time:       "HH:MM" string — scheduled arrival time
            current_status: existing status in DB (checked before overriding)

        Returns:
            New status string: "Arrived", "Departed", "Boarding", "Delayed", or "Scheduled"
        """
        now   = datetime.now()
        today = now.strftime("%Y-%m-%d")  # e.g. "2026-04-30"

        try:
            # Combine today's date with the HH:MM time strings to get full datetime objects
            dep_dt = datetime.strptime(f"{today} {dep_time}", "%Y-%m-%d %H:%M")
            arr_dt = datetime.strptime(f"{today} {arr_time}", "%Y-%m-%d %H:%M")

            # Handle overnight flights where arrival is after midnight
            # e.g. departure 23:00, arrival 01:30 → arr_dt must be the next day
            if arr_dt < dep_dt:
                arr_dt += timedelta(days=1)

        except Exception:
            # Unparseable time string — leave status unchanged to avoid data corruption
            return current_status

        # Minutes remaining until scheduled departure (negative = already departed)
        diff_dep = (dep_dt - now).total_seconds() / 60

        # ── Priority 1: Never override Cancelled ──────────────────────────────
        if current_status == "Cancelled":
            return "Cancelled"   # cancelled flights stay cancelled regardless of time

        # ── Priority 2: Arrived ───────────────────────────────────────────────
        if now > arr_dt:
            return "Arrived"     # current time is past the scheduled arrival time

        # ── Priority 3: Departed (airborne) ───────────────────────────────────
        if now > dep_dt:
            return "Departed"    # departed but not yet arrived

        # ── Priority 4: Boarding (very close to departure) ───────────────────
        if diff_dep <= 5:
            return "Boarding"    # gates close within 5 minutes — immediate boarding

        # ── Priority 5: Boarding with small delay chance ─────────────────────
        if diff_dep <= 45:
            # 10% chance of delay in the 45-minute pre-departure window
            if random.random() < 0.1:
                return "Delayed"
            return "Boarding"    # 90% of flights in this window are boarding normally

        # ── Priority 6: Scheduled with small delay chance ────────────────────
        if diff_dep <= 120:
            # 8% chance of delay for flights 45–120 minutes from departure
            if random.random() < 0.08:
                return "Delayed"
            return "Scheduled"   # most flights in this range are still scheduled

        # ── Priority 7: Far-future flight ─────────────────────────────────────
        # 5% chance of delay for flights more than 2 hours away
        if random.random() < 0.05:
            return "Delayed"

        return "Scheduled"       # default — flight is on schedule

    def run_update(self):
        """
        Execute one full status update cycle across all flights in the DB.
        Opens a single DB session, iterates all flights, computes new statuses,
        and commits only the rows that actually changed.
        """
        db      = DatabaseManager()  # get the singleton DB manager
        updated = 0                  # counter for changed rows (used for logging)

        try:
            with db.session_scope() as session:
                # Load all flights in one query — no pagination needed at this scale
                flights = session.query(FlightModel).all()

                for flight in flights:
                    # Compute what the status should be right now
                    new_status = self.compute_status(
                        flight.departure_time,  # "HH:MM" from DB
                        flight.arrival_time,    # "HH:MM" from DB
                        flight.status,          # current status (may be "Cancelled")
                    )

                    # Only update rows where the status actually changed
                    # This minimizes dirty writes and DB I/O
                    if new_status != flight.status:
                        flight.status = new_status  # SQLAlchemy detects this as dirty
                        updated += 1                # track how many rows we're changing

            # Log only if something actually changed — avoids noisy logs every 60s
            if updated > 0:
                print(f"[StatusUpdater] Updated {updated} flight statuses")

        except Exception as e:
            # Catch all errors so the background task never crashes the API process
            print(f"[StatusUpdater] Error: {e}")


async def status_update_loop():
    """
    Async loop that runs the status updater every 60 seconds.
    Registered as an asyncio task in app.py's lifespan handler.
    Uses asyncio.sleep() (non-blocking) instead of time.sleep()
    to avoid blocking the FastAPI event loop.
    """
    updater = StatusUpdater()
    print("[StatusUpdater] Started — updating statuses every 60 seconds")

    while True:
        await asyncio.sleep(60)   # yield control to the event loop for 60 seconds
        updater.run_update()      # run synchronous DB update after sleep completes