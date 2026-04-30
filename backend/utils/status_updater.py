"""
status_updater.py — Background task that updates flight statuses every minute.
Enhanced with realistic delay simulation (fixed priority).
"""

import asyncio
import random
from datetime import datetime, timedelta
from core.database import DatabaseManager
from models.models import FlightModel


class StatusUpdater:
    """
    Background task that updates flight statuses every 60 seconds.
    """

    @staticmethod
    def compute_status(dep_time: str, arr_time: str, current_status: str) -> str:
        """
        Compute realistic flight status with correct priority.
        """

        now = datetime.now()
        today = now.strftime("%Y-%m-%d")

        try:
            dep_dt = datetime.strptime(f"{today} {dep_time}", "%Y-%m-%d %H:%M")
            arr_dt = datetime.strptime(f"{today} {arr_time}", "%Y-%m-%d %H:%M")

            # Handle overnight flights
            if arr_dt < dep_dt:
                arr_dt += timedelta(days=1)

        except Exception:
            return current_status

        diff_dep = (dep_dt - now).total_seconds() / 60  # minutes

        # ❌ Never override Cancelled
        if current_status == "Cancelled":
            return "Cancelled"

        # 🟢 NORMAL STATUS FLOW FIRST (IMPORTANT FIX)

        if now > arr_dt:
            return "Arrived"

        if now > dep_dt:
            return "Departed"

        # 🔥 BOARDING WINDOW
        if diff_dep <= 5:
            return "Boarding"

        if diff_dep <= 45:
            # small delay chance
            if random.random() < 0.1:
                return "Delayed"
            return "Boarding"

        # 🔥 SCHEDULED WINDOW
        if diff_dep <= 120:
            if random.random() < 0.08:
                return "Delayed"
            return "Scheduled"

        # 🔥 FAR FUTURE
        if random.random() < 0.05:
            return "Delayed"

        return "Scheduled"

    def run_update(self):
        """Run one update cycle."""
        db = DatabaseManager()
        updated = 0

        try:
            with db.session_scope() as session:
                flights = session.query(FlightModel).all()

                for flight in flights:
                    new_status = self.compute_status(
                        flight.departure_time,
                        flight.arrival_time,
                        flight.status,
                    )

                    if new_status != flight.status:
                        flight.status = new_status
                        updated += 1

            if updated > 0:
                print(f"[StatusUpdater] Updated {updated} flight statuses")

        except Exception as e:
            print(f"[StatusUpdater] Error: {e}")


async def status_update_loop():
    """
    Async loop that updates flight statuses every 60 seconds.
    """
    updater = StatusUpdater()
    print("[StatusUpdater] Started — updating statuses every 60 seconds")

    while True:
        await asyncio.sleep(60)
        updater.run_update()