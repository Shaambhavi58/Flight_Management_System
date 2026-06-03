"""
flight_publisher.py — HYD Only Flight Data Publisher
====================================================

Generates clean Hyderabad Airport data only.

Rules:
- Only HYD airport
- Selected operating airlines only
- Arrivals: origin -> Hyderabad (HYD), carousel for Arrived flights
- Departures: Hyderabad (HYD) -> destination, gate + makeup_area mandatory
- Realistic statuses: Arrived, Departed, Scheduled, Boarding, Delayed, Cancelled
"""

import os
import json
import time
import random
import argparse
import pika
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
EXCHANGE_NAME = "flights.morning"
QUEUE_NAME = "morning_flights_queue"
ROUTING_KEY = "flight.morning.data"

IST = timezone(timedelta(hours=5, minutes=30))

AIRPORTS = [
    {"iata": "HYD", "airport_id": 5, "city": "Hyderabad"},
]

AIRLINE_NAMES = {
    "6E": "IndiGo",
    "AI": "Air India",
    "QP": "Akasa Air",
    "EK": "Emirates",
    "QA": "Qatar Airways",
    "AI1": "Air India Express",
    "AA1": "Alliance Air",
    "F": "Fly91",
}

FLIGHT_PREFIXES = {
    "6E": ("6E", 100, 9999),
    "AI": ("AI", 100, 9999),
    "QP": ("QP", 1000, 1999),
    "EK": ("EK", 500, 599),
    "QA": ("QR", 400, 999),
    "AI1": ("IX", 100, 999),
    "AA1": ("9I", 500, 999),
    "F": ("IC", 3000, 5999),
}

TERMINAL_MAP = {
    "6E": "T1",
    "AI": "T2",
    "QP": "T1",
    "EK": "T3",
    "QA": "T3",
    "AI1": "T2",
    "AA1": "T1",
    "F": "T1",
}

GATE_RANGES = {
    "T1": (1, 24),
    "T2": (25, 40),
    "T3": (41, 60),
}

CAROUSEL_RANGES = {
    "T1": (1, 8),
    "T2": (9, 12),
    "T3": (13, 16),
}

MAKEUP_AREAS = {
    "T1": (1, 12),
    "T2": (13, 18),
    "T3": (19, 24),
}

DELAY_REASONS = [
    "Air traffic congestion",
    "Late inbound aircraft",
    "Ground handling delay",
    "Weather disruption",
    "Technical inspection",
    "Crew scheduling adjustment",
    "Baggage loading delay",
]

HYD_ROUTES = {
    "6E": [
        ("Delhi (DEL)", 155), ("Mumbai (BOM)", 90), ("Bengaluru (BLR)", 60),
        ("Chennai (MAA)", 70), ("Kolkata (CCU)", 145), ("Goa (GOI)", 80),
        ("Pune (PNQ)", 85), ("Ahmedabad (AMD)", 105), ("Jaipur (JAI)", 125),
        ("Lucknow (LKO)", 115), ("Patna (PAT)", 125), ("Vijayawada (VGA)", 55),
        ("Tirupati (TIR)", 60), ("Visakhapatnam (VTZ)", 70), ("Coimbatore (CJB)", 95),
        ("Kochi (COK)", 95), ("Bhubaneswar (BBI)", 100), ("Nagpur (NAG)", 70),
    ],
    "AI": [
        ("Delhi (DEL)", 155), ("Mumbai (BOM)", 90), ("Bengaluru (BLR)", 60),
        ("Chennai (MAA)", 70), ("Kolkata (CCU)", 145), ("Pune (PNQ)", 85),
        ("Visakhapatnam (VTZ)", 70),
    ],
    "QP": [
        ("Delhi (DEL)", 160), ("Mumbai (BOM)", 90), ("Bengaluru (BLR)", 60),
        ("Goa (GOI)", 80), ("Ahmedabad (AMD)", 105),
    ],
    "EK": [
        ("Dubai (DXB)", 210),
    ],
    "QA": [
        ("Doha (DOH)", 250),
    ],
    "AI1": [
        ("Dubai (DXB)", 215), ("Jeddah (JED)", 300), ("Thiruvananthapuram (TRV)", 105),
    ],
    "AA1": [
        ("Bengaluru (BLR)", 70), ("Tirupati (TIR)", 60), ("Vijayawada (VGA)", 55),
    ],
    "F": [
        ("Goa (GOI)", 85), ("Vijayawada (VGA)", 55), ("Rajahmundry (RJA)", 60),
    ],
}


class DailyScheduleGenerator:
    def __init__(self):
        self.today = datetime.now().date()
        self.now = datetime.now()

    def _get_batch_name(self, dep_time: str) -> str:
        hour = int(dep_time.split(":")[0])
        if hour < 12:
            return "Morning"
        if hour < 18:
            return "Afternoon"
        return "Evening"

    def _get_terminal(self, airline_code: str) -> str:
        return TERMINAL_MAP.get(airline_code, "T1")

    def _get_gate(self, flight_number: str, terminal: str) -> str:
        low, high = GATE_RANGES.get(terminal, (1, 24))
        seed = abs(hash(f"{flight_number}-{self.today}-gate"))
        return f"G{(seed % (high - low + 1)) + low}"

    def _get_carousel(self, flight_number: str, terminal: str) -> str:
        low, high = CAROUSEL_RANGES.get(terminal, (1, 8))
        seed = abs(hash(f"{flight_number}-{self.today}-carousel"))
        return f"C{(seed % (high - low + 1)) + low}"

    def _get_makeup_area(self, flight_number: str, terminal: str) -> str:
        low, high = MAKEUP_AREAS.get(terminal, (1, 12))
        seed = abs(hash(f"{flight_number}-{self.today}-makeup"))
        return f"M{(seed % (high - low + 1)) + low}"

    def _make_flight_number(self, airline_code: str, idx: int, flight_type: str, used_numbers: set) -> str:
        prefix, low, high = FLIGHT_PREFIXES[airline_code]
        for offset in range(100):
            seed = abs(hash(f"{airline_code}-{idx}-{flight_type}-{self.today}-{offset}"))
            fnum = f"{prefix}{(seed % (high - low + 1)) + low}"
            if fnum not in used_numbers:
                used_numbers.add(fnum)
                return fnum
        
        fnum = f"{prefix}{random.randint(low, high)}"
        used_numbers.add(fnum)
        return fnum

    def _time_to_datetime(self, time_str: str) -> datetime:
        dt = datetime.strptime(f"{self.today} {time_str}", "%Y-%m-%d %H:%M")

        hour = int(time_str.split(":")[0])

        # Evening me next early morning flights ko tomorrow treat karo
        if self.now.hour >= 18 and hour < 6:
            dt += timedelta(days=1)

        return dt

    def _status_for_flight(
        self,
        flight_number: str,
        flight_type: str,
        departure_time: str,
        arrival_time: str,
    ):
        dep_dt = self._time_to_datetime(departure_time)
        arr_dt = self._time_to_datetime(arrival_time)

        if arr_dt < dep_dt:
            arr_dt += timedelta(days=1)

        now = self.now
        diff_dep = (dep_dt - now).total_seconds() / 60

        seed = abs(hash(f"{flight_number}-{self.today}-status"))
        cancelled_flag = seed % 100 < 2
        delayed_flag = seed % 100 in range(10, 18)

        if cancelled_flag and now < dep_dt:
            return "Cancelled", 0, None

        if delayed_flag and -30 <= diff_dep <= 240:
            delay_minutes = [15, 25, 35, 45, 60, 75][seed % 6]
            reason = DELAY_REASONS[seed % len(DELAY_REASONS)]
            actual_dep = dep_dt + timedelta(minutes=delay_minutes)
            actual_arr = arr_dt + timedelta(minutes=delay_minutes)

            if now < actual_dep:
                return "Delayed", delay_minutes, reason
            if actual_dep <= now < actual_arr:
                return "Departed", 0, None
            return "Arrived", 0, None

        if flight_type == "arrival":
            if now >= arr_dt:
                return "Arrived", 0, None
            if now >= dep_dt:
                return "Departed", 0, None
            if diff_dep <= 45:
                return "Boarding", 0, None
            return "Scheduled", 0, None

        if flight_type == "departure":
            if now >= dep_dt:
                return "Departed", 0, None
            if diff_dep <= 45:
                return "Boarding", 0, None
            return "Scheduled", 0, None

        return "Scheduled", 0, None

    def _build_departure_slots(self):
        slots = []
        for h in range(0, 24):
            for m in [0, 6, 12, 18, 24, 30, 36, 42, 48, 54]:
                slots.append(f"{h:02d}:{m:02d}")
        return slots

    def _build_arrival_slots(self):
        slots = []
        for h in range(0, 24):
            for m in [3, 9, 15, 21, 27, 33, 39, 45, 51, 57]:
                slots.append(f"{h:02d}:{m:02d}")
        return slots

    def _weighted_airlines(self):
        cycle = (
            ["6E"] * 67
            + ["AI"] * 45
            + ["QP"] * 28
            + ["EK"] * 22
            + ["QA"] * 20
            + ["AI1"] * 22
            + ["AA1"] * 18
            + ["F"] * 18
        )
        random.seed(42)
        random.shuffle(cycle)
        return cycle

    def generate(self, airport_id: int, airport_iata: str) -> list:
        if airport_iata != "HYD":
            return []

        flights = []
        used_keys = set()
        used_fnums = set()

        departure_slots = self._build_departure_slots()
        arrival_slots = self._build_arrival_slots()
        airline_cycle = self._weighted_airlines()

        # Departures: Hyderabad -> destination
        for idx, dep_time in enumerate(departure_slots):
            airline_code = airline_cycle[idx % len(airline_cycle)]
            routes = HYD_ROUTES[airline_code]
            destination, duration = routes[idx % len(routes)]

            dep_dt = datetime.strptime(f"2000-01-01 {dep_time}", "%Y-%m-%d %H:%M")
            arr_time = (dep_dt + timedelta(minutes=duration)).strftime("%H:%M")

            flight_number = self._make_flight_number(airline_code, idx, "departure", used_fnums)
            terminal = self._get_terminal(airline_code)
            gate = self._get_gate(flight_number, terminal)
            makeup = self._get_makeup_area(flight_number, terminal)

            status, delay_minutes, delay_reason = self._status_for_flight(
                flight_number, "departure", dep_time, arr_time
            )

            key = (flight_number, "departure", "Hyderabad (HYD)", destination, dep_time)
            if key in used_keys:
                continue
            used_keys.add(key)

            flights.append({
                "flight_number": flight_number,
                "airline_code": airline_code,
                "airport_id": airport_id,
                "origin": "Hyderabad (HYD)",
                "destination": destination,
                "departure_time": dep_time,
                "arrival_time": arr_time,
                "gate_number": gate,
                "terminal_number": terminal,
                "carousel_number": None,
                "makeup_area": makeup,
                "status": status,
                "flight_type": "departure",
                "delay_minutes": delay_minutes,
                "delay_reason": delay_reason,
                "batch_name": self._get_batch_name(dep_time),
            })

        # Arrivals: origin -> Hyderabad
        for idx, arr_time in enumerate(arrival_slots):
            airline_code = airline_cycle[idx % len(airline_cycle)]
            routes = HYD_ROUTES[airline_code]
            origin, duration = routes[idx % len(routes)]

            arr_dt = datetime.strptime(f"2000-01-01 {arr_time}", "%Y-%m-%d %H:%M")
            dep_time = (arr_dt - timedelta(minutes=duration)).strftime("%H:%M")

            flight_number = self._make_flight_number(airline_code, idx, "arrival", used_fnums)
            terminal = self._get_terminal(airline_code)
            gate = self._get_gate(flight_number, terminal)

            status, delay_minutes, delay_reason = self._status_for_flight(
                flight_number, "arrival", dep_time, arr_time
            )

            # Arrivals always have a carousel
            carousel = self._get_carousel(flight_number, terminal)

            key = (flight_number, "arrival", origin, "Hyderabad (HYD)", arr_time)
            if key in used_keys:
                continue
            used_keys.add(key)

            flights.append({
                "flight_number": flight_number,
                "airline_code": airline_code,
                "airport_id": airport_id,
                "origin": origin,
                "destination": "Hyderabad (HYD)",
                "departure_time": dep_time,
                "arrival_time": arr_time,
                "gate_number": gate,
                "terminal_number": terminal,
                "carousel_number": carousel,
                "makeup_area": None,
                "status": status,
                "flight_type": "arrival",
                "delay_minutes": delay_minutes,
                "delay_reason": delay_reason,
                "batch_name": self._get_batch_name(dep_time),
            })

        self._force_demo_status_balance(flights)

        print(f"[Generator] HYD -> {len(flights)} clean flights generated")
        return flights

    def _force_demo_status_balance(self, flights: list):
        """
        Safety for demo:
        ensure Scheduled, Boarding, and Delayed are not zero.
        """
        departures = [f for f in flights if f["flight_type"] == "departure"]
        future_departures = [
            f for f in departures
            if f["status"] in ("Scheduled", "Boarding", "Delayed")
        ]

        if not future_departures:
            future_departures = departures[-30:]

        scheduled_count = sum(1 for f in flights if f["status"] == "Scheduled")
        boarding_count = sum(1 for f in flights if f["status"] == "Boarding")
        delayed_count = sum(1 for f in flights if f["status"] == "Delayed")

        if scheduled_count == 0 and len(future_departures) >= 1:
            future_departures[-1]["status"] = "Scheduled"
            future_departures[-1]["delay_minutes"] = 0
            future_departures[-1]["delay_reason"] = None

        if boarding_count == 0 and len(future_departures) >= 2:
            future_departures[-2]["status"] = "Boarding"
            future_departures[-2]["delay_minutes"] = 0
            future_departures[-2]["delay_reason"] = None

        if delayed_count == 0 and len(future_departures) >= 3:
            future_departures[-3]["status"] = "Delayed"
            future_departures[-3]["delay_minutes"] = 35
            future_departures[-3]["delay_reason"] = "Ground handling delay"


class FlightPublisher:
    def __init__(self):
        self._connection = None
        self._channel = None

    def connect(self):
        self._connection = pika.BlockingConnection(
            pika.ConnectionParameters(host=RABBITMQ_HOST, heartbeat=600)
        )
        self._channel = self._connection.channel()
        self._channel.exchange_declare(
            exchange=EXCHANGE_NAME,
            exchange_type="direct",
            durable=True,
        )
        self._channel.queue_declare(queue=QUEUE_NAME, durable=True)
        self._channel.queue_bind(
            queue=QUEUE_NAME,
            exchange=EXCHANGE_NAME,
            routing_key=ROUTING_KEY,
        )

    def publish(self, flight: dict):
        self._channel.basic_publish(
            exchange=EXCHANGE_NAME,
            routing_key=ROUTING_KEY,
            body=json.dumps(flight),
            properties=pika.BasicProperties(
                delivery_mode=2,
                content_type="application/json",
            ),
        )

    def close(self):
        try:
            if self._connection and not self._connection.is_closed:
                self._connection.close()
        except Exception:
            pass


class FlightDataOrchestrator:
    def __init__(self):
        self._last_run_date = None

    def run_once(self, triggered_by: str = "system") -> dict:
        start_time = time.monotonic()
        today = datetime.now()

        print("\n" + "=" * 60)
        print(f"[Sync Live] HYD clean data sync started by {triggered_by}")
        print(f"[Sync Live] Time: {today.strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)

        generator = DailyScheduleGenerator()
        publisher = FlightPublisher()

        all_flights = []
        airport_summary = {}

        try:
            publisher.connect()
            print("[Sync Live] RabbitMQ connected")
        except Exception as e:
            print(f"[Sync Live] RabbitMQ connection failed: {e}")
            return {"error": str(e), "published": 0}

        for airport in AIRPORTS:
            iata = airport["iata"]
            airport_id = airport["airport_id"]

            flights = generator.generate(airport_id, iata)
            all_flights.extend(flights)
            airport_summary[iata] = len(flights)

        published_count = 0
        for flight in all_flights:
            try:
                publisher.publish(flight)
                published_count += 1
            except Exception as e:
                print(f"[Sync Live] Publish error: {flight.get('flight_number')}: {e}")

        publisher.close()

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        self._last_run_date = today.date()

        print(f"[Sync Live] HYD -> {published_count} flights published")
        print(f"[Sync Live] Completed in {elapsed_ms}ms")
        print("=" * 60 + "\n")

        return {
            "date": str(self._last_run_date),
            "timestamp": today.isoformat(),
            "generated": len(all_flights),
            "published": published_count,
            "by_airport": airport_summary,
            "elapsed_ms": elapsed_ms,
            "triggered_by": triggered_by,
        }

    def run_daily(self):
        print("[Sync Live] Daily HYD mode started")
        while True:
            try:
                today = datetime.now().date()

                if self._last_run_date != today:
                    self.run_once(triggered_by="daily-scheduler")

                now = datetime.now()
                midnight = datetime.combine(today + timedelta(days=1), datetime.min.time())
                sleep_secs = (midnight - now).total_seconds()

                print(
                    f"[Sync Live] Next reset in "
                    f"{int(sleep_secs // 3600)}h {int((sleep_secs % 3600) // 60)}m"
                )

                time.sleep(min(sleep_secs + 5, 1800))

            except KeyboardInterrupt:
                print("\n[Sync Live] Daily mode stopped")
                break
            except Exception as e:
                print(f"[Sync Live] Error: {e}")
                time.sleep(300)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HYD Flight Data Publisher")
    parser.add_argument("--daily", action="store_true", help="Run daily mode")
    parser.add_argument("--airport", type=str, default="HYD", help="Only HYD supported")
    args = parser.parse_args()

    orchestrator = FlightDataOrchestrator()

    if args.daily:
        orchestrator.run_daily()
    else:
        orchestrator.run_once(triggered_by="cli")