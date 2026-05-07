"""
services/analytics_service.py
==============================
AnalyticsService — Business logic for the enterprise Operations Dashboard.

Provides aggregated, real-time metrics by querying the flights, airports,
and airlines tables. All methods open their own DB session via the
DatabaseManager singleton and return plain Python dicts/lists ready for
JSON serialization by the analytics controller.

Used by: controllers/analytics_controller.py → GET /analytics/dashboard
"""

from sqlalchemy import func
from core.database import DatabaseManager
from models.models import FlightModel, AirportModel, AirlineModel
from datetime import datetime

class AnalyticsService:
    """
    Aggregates flight data from the MySQL database for the operations dashboard.
    All queries are read-only and use SQLAlchemy's session_scope for clean connections.
    """

    def __init__(self):
        # Shared DB manager (singleton) — reuses the same connection pool as the rest of the app
        self.db = DatabaseManager()

    def get_kpis(self):
        """
        Return headline KPI counts used for the top dashboard cards.
        Each metric is a separate scalar COUNT query for clarity.
        """
        with self.db.session_scope() as session:
            # Total number of flights across ALL airports and statuses
            total = session.query(func.count(FlightModel.id)).scalar()

            # Active flights = those currently in motion (boarding, departed, or delayed)
            active = session.query(func.count(FlightModel.id)).filter(
                FlightModel.status.in_(["Boarding", "Departed", "Delayed"])
            ).scalar()

            # Delayed flights — subset of active that have not yet departed on time
            delayed = session.query(func.count(FlightModel.id)).filter(
                FlightModel.status == "Delayed"
            ).scalar()

            # Boarding flights — at gate, about to depart
            boarding = session.query(func.count(FlightModel.id)).filter(
                FlightModel.status == "Boarding"
            ).scalar()

            # Arrived flights — have landed at destination
            arrived = session.query(func.count(FlightModel.id)).filter(
                FlightModel.status == "Arrived"
            ).scalar()

            # Distinct airlines that have at least one flight in the DB
            active_airlines = session.query(
                func.count(func.distinct(FlightModel.airline_id))
            ).scalar()

            return {
                "total_flights":   total,
                "active_flights":  active,
                "delayed_flights": delayed,
                "boarding_flights": boarding,
                "arrived_flights": arrived,
                "active_airlines": active_airlines,
            }

    def get_status_distribution(self):
        """
        Return flight counts grouped by status (Scheduled, Boarding, Departed, etc.).
        Used to render the doughnut chart in the analytics dashboard.
        Each row in the result is a (status, count) pair.
        """
        with self.db.session_scope() as session:
            # GROUP BY status so we get one row per distinct status value
            result = session.query(
                FlightModel.status,
                func.count(FlightModel.id)
            ).group_by(FlightModel.status).all()

            # Debug log — visible in server console for quick validation
            print("\n[Analytics] Status Distribution:")
            for status, count in result:
                print(f"  {status}: {count}")

            # Return a list of dicts for easy JSON serialization
            return [{"status": status, "count": count} for status, count in result]

    def get_flights_per_airline(self):
        """
        Return the total flight count for each airline.
        Used to render the bar chart comparing airline traffic volume.
        Joins AirlineModel → FlightModel so we get both code and full name.
        """
        with self.db.session_scope() as session:
            # JOIN airlines with flights, GROUP BY airline to get per-airline counts.
            # We group by AirlineModel.id (the PK) as well as code/name to satisfy
            # SQL GROUP BY rules without losing the display fields.
            result = session.query(
                AirlineModel.code,
                AirlineModel.name,
                func.count(FlightModel.id)
            ).join(FlightModel).group_by(
                AirlineModel.id, AirlineModel.code, AirlineModel.name
            ).all()

            # Debug log for server-side validation
            print("\n[Analytics] Flights per Airline:")
            for code, name, count in result:
                print(f"  {code} | {name}: {count}")

            return [{"code": code, "name": name, "count": count} for code, name, count in result]

    def get_airport_comparison(self):
        """
        Return the number of ACTIVE flights (Boarding / Departed / Delayed)
        for each airport. Used to render the horizontal bar chart.

        Uses OUTER JOIN so airports with zero active flights still appear in
        the result (they would be excluded by an INNER JOIN).
        The filter is applied inside the JOIN condition, not as a WHERE clause,
        which is necessary to keep airports with 0 active flights in the output.
        """
        with self.db.session_scope() as session:
            # OUTER JOIN airports ← flights, filtered to active statuses only.
            # Grouping by both airport id and code satisfies GROUP BY without losing code.
            result = session.query(
                AirportModel.id,
                AirportModel.code,
                func.count(FlightModel.id)
            ).outerjoin(
                FlightModel,
                # Filter in the JOIN condition so airports with 0 active flights
                # are still returned (COUNT = 0), not silently omitted.
                (AirportModel.id == FlightModel.airport_id) &
                (FlightModel.status.in_(["Boarding", "Departed", "Delayed"]))
            ).group_by(AirportModel.id, AirportModel.code).all()

            # Server-side audit log for validating counts during development
            print("\n[Analytics] Active Flights by Airport (Audit):")
            for aid, code, count in result:
                print(f"  airport_id: {aid} | airport_code: {code} | active_flights: {count}")

            return [{"airport": code, "active_flights": count} for _, code, count in result]

    def get_live_alerts(self):
        """
        Return the 10 most recent operational alerts (Delayed or Boarding flights).
        Used to populate the live-alerts feed on the dashboard sidebar.

        JOIN with AirportModel so we can display the airport code in each alert message.
        ORDER BY id DESC gives us the newest flights first (most recently inserted).
        """
        with self.db.session_scope() as session:
            # Fetch flights with Delayed or Boarding status, newest 10 only
            alerts = session.query(FlightModel, AirportModel).join(AirportModel).filter(
                FlightModel.status.in_(["Delayed", "Boarding"])
            ).order_by(FlightModel.id.desc()).limit(10).all()

            alert_list = []
            for flight, airport in alerts:
                if flight.status == "Delayed":
                    # Warning alert — gate is delayed
                    msg = f"⚠ {airport.code} Gate {flight.gate_number} delayed ({flight.flight_number})"
                    alert_type = "warning"
                else:
                    # Info alert — boarding in progress
                    msg = f"🛫 {airport.code} boarding traffic ({flight.flight_number})"
                    alert_type = "info"

                alert_list.append({"message": msg, "type": alert_type})

            return alert_list

    def get_batch_email_monitoring(self):
        """
        Return the status of each batch email window for the dashboard monitor.

        Batch time windows (matches worker.py BATCH_SCHEDULE exactly):
          Morning   → flights with dep 00:00–11:59, email sent at 12:00 PM
          Afternoon → flights with dep 12:00–17:59, email sent at 06:00 PM
          Evening   → flights with dep 18:00–23:59, email sent at 11:59 PM

        Status transitions (clock-based):
          SCHEDULED → batch has not started yet (too early in the day)
          PENDING   → flights are accumulating, email not yet sent
          SENT      → send time has passed; email was dispatched by worker.py
        """
        with self.db.session_scope() as session:
            # ── Step 1: Count flights per batch window using departure_time string comparison ──
            # String comparison works here because departure_time is stored as "HH:MM" (zero-padded),
            # which sorts lexicographically the same as numerically.
            morning_count = session.query(func.count(FlightModel.id)).filter(
                FlightModel.departure_time >= "00:00",
                FlightModel.departure_time <  "12:00"
            ).scalar()

            afternoon_count = session.query(func.count(FlightModel.id)).filter(
                FlightModel.departure_time >= "12:00",
                FlightModel.departure_time <  "18:00"
            ).scalar()

            evening_count = session.query(func.count(FlightModel.id)).filter(
                FlightModel.departure_time >= "18:00",
                FlightModel.departure_time <= "23:59"
            ).scalar()

            # ── Step 2: Determine send status based on current wall-clock time ──
            now = datetime.now()
            h, m = now.hour, now.minute  # current hour and minute

            def is_after(target_h, target_m):
                """Returns True if current time >= (target_h:target_m)."""
                return h > target_h or (h == target_h and m >= target_m)

            # Morning batch:
            #   Before 12:00 → PENDING (flights are being accumulated)
            #   12:00+       → SENT    (email was fired by worker.py at noon)
            morning_status = "SENT" if is_after(12, 0) else "PENDING"

            # Afternoon batch:
            #   Before 12:00 → SCHEDULED (batch window hasn't opened yet)
            #   12:00–17:59  → PENDING   (flights accumulating)
            #   18:00+       → SENT      (email dispatched at 6 PM)
            if is_after(18, 0):
                afternoon_status = "SENT"
            elif is_after(12, 0):
                afternoon_status = "PENDING"
            else:
                afternoon_status = "SCHEDULED"

            # Evening batch:
            #   Before 18:00 → SCHEDULED (batch window hasn't opened yet)
            #   18:00–23:58  → PENDING   (flights accumulating)
            #   23:59+       → SENT      (email dispatched at midnight-1)
            if is_after(23, 59):
                evening_status = "SENT"
            elif is_after(18, 0):
                evening_status = "PENDING"
            else:
                evening_status = "SCHEDULED"

            # Return structured list for dashboard rendering
            return [
                {
                    "batch":   "Morning Batch",
                    "time":    "12:00 PM",
                    "flights": morning_count,
                    "status":  morning_status,
                },
                {
                    "batch":   "Afternoon Batch",
                    "time":    "06:00 PM",
                    "flights": afternoon_count,
                    "status":  afternoon_status,
                },
                {
                    "batch":   "Evening Batch",
                    "time":    "11:59 PM",
                    "flights": evening_count,
                    "status":  evening_status,
                },
            ]
