from sqlalchemy import func
from core.database import DatabaseManager
from models.models import FlightModel, AirportModel, AirlineModel, GateModel
from datetime import datetime

HYD_AIRPORT_ID = 5


class AnalyticsService:
    def __init__(self):
        self.db = DatabaseManager()

    def get_kpis(self):
        with self.db.session_scope() as session:
            total = session.query(func.count(FlightModel.id)).filter(
                FlightModel.airport_id == HYD_AIRPORT_ID
            ).scalar() or 0

            scheduled = session.query(func.count(FlightModel.id)).filter(
                FlightModel.airport_id == HYD_AIRPORT_ID,
                FlightModel.status == "Scheduled"
            ).scalar() or 0

            boarding = session.query(func.count(FlightModel.id)).filter(
                FlightModel.airport_id == HYD_AIRPORT_ID,
                FlightModel.status == "Boarding"
            ).scalar() or 0

            delayed = session.query(func.count(FlightModel.id)).filter(
                FlightModel.airport_id == HYD_AIRPORT_ID,
                FlightModel.status == "Delayed"
            ).scalar() or 0

            arrived = session.query(func.count(FlightModel.id)).filter(
                FlightModel.airport_id == HYD_AIRPORT_ID,
                FlightModel.status == "Arrived"
            ).scalar() or 0

            cancelled = session.query(func.count(FlightModel.id)).filter(
                FlightModel.airport_id == HYD_AIRPORT_ID,
                FlightModel.status == "Cancelled"
            ).scalar() or 0

            departure = session.query(func.count(FlightModel.id)).filter(
                FlightModel.airport_id == HYD_AIRPORT_ID,
                FlightModel.flight_type == "departure"
            ).scalar() or 0

            active = scheduled + boarding + delayed

            avg_delay = session.query(func.avg(FlightModel.delay_minutes)).filter(
                FlightModel.airport_id == HYD_AIRPORT_ID,
                FlightModel.status == "Delayed",
                FlightModel.delay_minutes.is_not(None),
                FlightModel.delay_minutes > 0
            ).scalar()

            active_carousels = session.query(
                func.count(func.distinct(FlightModel.carousel_number))
            ).filter(
                FlightModel.airport_id == HYD_AIRPORT_ID,
                FlightModel.status == "Arrived",
                FlightModel.carousel_number.is_not(None),
                FlightModel.carousel_number != ""
            ).scalar() or 0

            on_time_count = session.query(func.count(FlightModel.id)).filter(
                FlightModel.airport_id == HYD_AIRPORT_ID,
                FlightModel.status.notin_(["Delayed", "Cancelled"])
            ).scalar() or 0

            on_time_percentage = round((on_time_count / total * 100), 1) if total else 100.0
            avg_delay_duration = round(float(avg_delay), 1) if avg_delay else 0.0

            return {
                "total_flights": total,
                "active_flights": active,
                "delayed_flights": delayed,
                "boarding_flights": boarding,
                "arrived_flights": arrived,
                "scheduled_flights": scheduled,
                "cancelled_flights": cancelled,
                "departure_flights": departure,
                "active_carousels": active_carousels,
                "on_time_percentage": on_time_percentage,
                "avg_delay_duration": avg_delay_duration,
            }

    def get_status_distribution(self):
        with self.db.session_scope() as session:
            result = session.query(
                FlightModel.status,
                func.count(FlightModel.id)
            ).filter(
                FlightModel.airport_id == HYD_AIRPORT_ID
            ).group_by(FlightModel.status).all()

            return [{"status": status, "count": count} for status, count in result]

    def get_flights_per_airline(self):
        with self.db.session_scope() as session:
            result = session.query(
                AirlineModel.code,
                AirlineModel.name,
                func.count(FlightModel.id)
            ).join(
                FlightModel, AirlineModel.id == FlightModel.airline_id
            ).filter(
                FlightModel.airport_id == HYD_AIRPORT_ID
            ).group_by(
                AirlineModel.id, AirlineModel.code, AirlineModel.name
            ).all()

            return [{"code": code, "name": name, "count": count} for code, name, count in result]

    def get_airport_comparison(self):
        with self.db.session_scope() as session:
            result = session.query(
                AirportModel.code,
                func.count(FlightModel.id)
            ).join(
                FlightModel, AirportModel.id == FlightModel.airport_id
            ).filter(
                FlightModel.airport_id == HYD_AIRPORT_ID,
                FlightModel.status.in_(["Scheduled", "Boarding", "Delayed"])
            ).group_by(
                AirportModel.code
            ).all()

            return [{"airport": code, "active_flights": count} for code, count in result]

    def get_live_alerts(self):
        from services.alert_service import AlertService
        alert_service = AlertService()
        return alert_service.get_active_alerts()

    def get_batch_email_monitoring(self):
        with self.db.session_scope() as session:
            morning_count = session.query(func.count(FlightModel.id)).filter(
                FlightModel.airport_id == HYD_AIRPORT_ID,
                FlightModel.departure_time >= "00:00",
                FlightModel.departure_time < "12:00"
            ).scalar() or 0

            afternoon_count = session.query(func.count(FlightModel.id)).filter(
                FlightModel.airport_id == HYD_AIRPORT_ID,
                FlightModel.departure_time >= "12:00",
                FlightModel.departure_time < "18:00"
            ).scalar() or 0

            evening_count = session.query(func.count(FlightModel.id)).filter(
                FlightModel.airport_id == HYD_AIRPORT_ID,
                FlightModel.departure_time >= "18:00",
                FlightModel.departure_time <= "23:59"
            ).scalar() or 0

            now = datetime.now()
            h, m = now.hour, now.minute

            def is_after(target_h, target_m):
                return h > target_h or (h == target_h and m >= target_m)

            morning_status = "SENT" if is_after(12, 0) else "PENDING"

            if is_after(18, 0):
                afternoon_status = "SENT"
            elif is_after(12, 0):
                afternoon_status = "PENDING"
            else:
                afternoon_status = "SCHEDULED"

            if is_after(23, 59):
                evening_status = "SENT"
            elif is_after(18, 0):
                evening_status = "PENDING"
            else:
                evening_status = "SCHEDULED"

            return [
                {"batch": "Morning Batch", "time": "12:00 PM", "flights": morning_count, "status": morning_status},
                {"batch": "Afternoon Batch", "time": "06:00 PM", "flights": afternoon_count, "status": afternoon_status},
                {"batch": "Evening Batch", "time": "11:59 PM", "flights": evening_count, "status": evening_status},
            ]

    def get_flights_per_terminal(self):
        with self.db.session_scope() as session:
            result = session.query(
                FlightModel.terminal_number,
                func.count(FlightModel.id)
            ).filter(
                FlightModel.airport_id == HYD_AIRPORT_ID
            ).group_by(FlightModel.terminal_number).all()

            return [{"terminal": term or "Unknown", "count": count} for term, count in result]

    def get_gate_status_distribution(self):
        with self.db.session_scope() as session:
            total_gates = session.query(func.count(GateModel.id)).filter(
                GateModel.airport_id == HYD_AIRPORT_ID
            ).scalar() or 0

            maintenance_gates = session.query(func.count(GateModel.id)).filter(
                GateModel.airport_id == HYD_AIRPORT_ID,
                func.lower(GateModel.status).in_(["maintenance", "under maintenance", "under_maintenance"])
            ).scalar() or 0

            occupied_gates = session.query(
                func.count(func.distinct(FlightModel.gate_number))
            ).filter(
                FlightModel.airport_id == HYD_AIRPORT_ID,
                FlightModel.status.in_(["Scheduled", "Boarding", "Delayed"]),
                FlightModel.gate_number.is_not(None),
                FlightModel.gate_number != ""
            ).scalar() or 0

            available_gates = max(total_gates - maintenance_gates - occupied_gates, 0)

            return {
                "total_gates": total_gates,
                "available_gates": available_gates,
                "occupied_gates": occupied_gates,
                "maintenance_gates": maintenance_gates,
            }

    def get_hourly_traffic(self):
        with self.db.session_scope() as session:
            flights = session.query(FlightModel.departure_time, FlightModel.arrival_time).filter(
                FlightModel.airport_id == HYD_AIRPORT_ID
            ).all()

            buckets = {
                "00:00 - 04:00": {"arrivals": 0, "departures": 0},
                "04:00 - 08:00": {"arrivals": 0, "departures": 0},
                "08:00 - 12:00": {"arrivals": 0, "departures": 0},
                "12:00 - 16:00": {"arrivals": 0, "departures": 0},
                "16:00 - 20:00": {"arrivals": 0, "departures": 0},
                "20:00 - 24:00": {"arrivals": 0, "departures": 0},
            }

            for dep_time, arr_time in flights:
                if dep_time:
                    try:
                        hour = int(dep_time.split(":")[0])
                        if 0 <= hour < 4:
                            buckets["00:00 - 04:00"]["departures"] += 1
                        elif 4 <= hour < 8:
                            buckets["04:00 - 08:00"]["departures"] += 1
                        elif 8 <= hour < 12:
                            buckets["08:00 - 12:00"]["departures"] += 1
                        elif 12 <= hour < 16:
                            buckets["12:00 - 16:00"]["departures"] += 1
                        elif 16 <= hour < 20:
                            buckets["16:00 - 20:00"]["departures"] += 1
                        else:
                            buckets["20:00 - 24:00"]["departures"] += 1
                    except Exception:
                        pass
                
                if arr_time:
                    try:
                        hour = int(arr_time.split(":")[0])
                        if 0 <= hour < 4:
                            buckets["00:00 - 04:00"]["arrivals"] += 1
                        elif 4 <= hour < 8:
                            buckets["04:00 - 08:00"]["arrivals"] += 1
                        elif 8 <= hour < 12:
                            buckets["08:00 - 12:00"]["arrivals"] += 1
                        elif 12 <= hour < 16:
                            buckets["12:00 - 16:00"]["arrivals"] += 1
                        elif 16 <= hour < 20:
                            buckets["16:00 - 20:00"]["arrivals"] += 1
                        else:
                            buckets["20:00 - 24:00"]["arrivals"] += 1
                    except Exception:
                        pass

            return [{"interval": k, "arrivals": v["arrivals"], "departures": v["departures"]} for k, v in buckets.items()]

    def get_carousel_utilization(self):
        with self.db.session_scope() as session:
            result = session.query(
                FlightModel.carousel_number,
                func.count(FlightModel.id)
            ).filter(
                FlightModel.airport_id == HYD_AIRPORT_ID,
                FlightModel.status == "Arrived",
                FlightModel.carousel_number.is_not(None),
                FlightModel.carousel_number != ""
            ).group_by(FlightModel.carousel_number).all()

            return [{"carousel": carousel, "assigned_flights": count} for carousel, count in result]