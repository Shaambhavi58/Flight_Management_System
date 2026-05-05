"""
AnalyticsService — Business logic for enterprise dashboard data.
Retrieves and aggregates real-time flight data.
"""

from sqlalchemy import func
from core.database import DatabaseManager
from models.models import FlightModel, AirportModel, AirlineModel
from datetime import datetime

class AnalyticsService:
    def __init__(self):
        self.db = DatabaseManager()

    def get_kpis(self):
        with self.db.session_scope() as session:
            total = session.query(func.count(FlightModel.id)).scalar()
            active = session.query(func.count(FlightModel.id)).filter(FlightModel.status.in_(["Boarding", "Departed", "Delayed"])).scalar()
            delayed = session.query(func.count(FlightModel.id)).filter(FlightModel.status == "Delayed").scalar()
            boarding = session.query(func.count(FlightModel.id)).filter(FlightModel.status == "Boarding").scalar()
            arrived = session.query(func.count(FlightModel.id)).filter(FlightModel.status == "Arrived").scalar()
            active_airlines = session.query(func.count(func.distinct(FlightModel.airline_id))).scalar()
            
            return {
                "total_flights": total,
                "active_flights": active,
                "delayed_flights": delayed,
                "boarding_flights": boarding,
                "arrived_flights": arrived,
                "active_airlines": active_airlines,
            }

    def get_status_distribution(self):
        with self.db.session_scope() as session:
            result = session.query(FlightModel.status, func.count(FlightModel.id)).group_by(FlightModel.status).all()
            
            print("\n[Analytics] Status Distribution:")
            for status, count in result:
                print(f"  {status}: {count}")
                
            return [{"status": status, "count": count} for status, count in result]

    def get_flights_per_airline(self):
        with self.db.session_scope() as session:
            # Group by airline ID and name to show real counts from DB
            result = session.query(
                AirlineModel.name, 
                func.count(FlightModel.id)
            ).join(FlightModel).group_by(AirlineModel.id, AirlineModel.name).all()
            
            print("\n[Analytics] Flights per Airline:")
            for name, count in result:
                print(f"  {name}: {count}")
                
            return [{"airline": name, "count": count} for name, count in result]

    def get_airport_comparison(self):
        with self.db.session_scope() as session:
            # Active flights per airport (Boarding, Departed, Delayed)
            # Must join flights.airport_id with airports.id to get codes
            result = session.query(
                AirportModel.id,
                AirportModel.code, 
                func.count(FlightModel.id)
            ).outerjoin(
                FlightModel, 
                (AirportModel.id == FlightModel.airport_id) & 
                (FlightModel.status.in_(["Boarding", "Departed", "Delayed"]))
            ).group_by(AirportModel.id, AirportModel.code).all()
            
            print("\n[Analytics] Active Flights by Airport (Audit):")
            for aid, code, count in result:
                print(f"  airport_id: {aid} | airport_code: {code} | active_flights: {count}")
            
            return [{"airport": code, "active_flights": count} for _, code, count in result]

    def get_live_alerts(self):
        with self.db.session_scope() as session:
            # Recent delayed or boarding flights
            alerts = session.query(FlightModel, AirportModel).join(AirportModel).filter(
                FlightModel.status.in_(["Delayed", "Boarding"])
            ).order_by(FlightModel.id.desc()).limit(10).all()
            
            alert_list = []
            for flight, airport in alerts:
                if flight.status == "Delayed":
                    msg = f"⚠ {airport.code} Gate {flight.gate_number} delayed ({flight.flight_number})"
                    alert_type = "warning"
                else:
                    msg = f"🛫 {airport.code} boarding traffic ({flight.flight_number})"
                    alert_type = "info"
                
                alert_list.append({"message": msg, "type": alert_type})
            return alert_list

    def get_batch_email_monitoring(self):
        with self.db.session_scope() as session:
            # ── 1. Count flights per batch using the canonical ranges ──────
            morning_count = session.query(func.count(FlightModel.id)).filter(
                FlightModel.departure_time >= "00:00", FlightModel.departure_time < "12:00"
            ).scalar()
            afternoon_count = session.query(func.count(FlightModel.id)).filter(
                FlightModel.departure_time >= "12:00", FlightModel.departure_time < "18:00"
            ).scalar()
            evening_count = session.query(func.count(FlightModel.id)).filter(
                FlightModel.departure_time >= "18:00", FlightModel.departure_time <= "23:59"
            ).scalar()
            
            now = datetime.now()
            h, m = now.hour, now.minute
            
            # Helper to check if current time is >= target time
            def is_after(target_h, target_m):
                return h > target_h or (h == target_h and m >= target_m)

            # ── 2. Determine statuses ──────────────────────────────────────
            # Morning: Pending until 11:59 AM, then SENT at 12:00 PM
            morning_status = "SENT" if is_after(12, 0) else "PENDING"
            
            # Afternoon: Scheduled before 12:00 PM, Pending until 5:59 PM, SENT at 6:00 PM
            if is_after(18, 0):
                afternoon_status = "SENT"
            elif is_after(12, 0):
                afternoon_status = "PENDING"
            else:
                afternoon_status = "SCHEDULED"
                
            # Evening: Scheduled before 6:00 PM, Pending until 11:58 PM, SENT at 11:59 PM
            if is_after(23, 59):
                evening_status = "SENT"
            elif is_after(18, 0):
                evening_status = "PENDING"
            else:
                evening_status = "SCHEDULED"

            return [
                {
                    "batch": "Morning Batch",
                    "time": "12:00 PM",
                    "flights": morning_count,
                    "status": morning_status
                },
                {
                    "batch": "Afternoon Batch",
                    "time": "06:00 PM",
                    "flights": afternoon_count,
                    "status": afternoon_status
                },
                {
                    "batch": "Evening Batch",
                    "time": "11:59 PM",
                    "flights": evening_count,
                    "status": evening_status
                }
            ]
