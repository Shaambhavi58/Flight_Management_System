"""
flight_publisher.py — External Flight Data Publisher v2
=======================================================
Fetches REAL flight routes from AviationStack API.
Generates today's FULL DAY schedule (00:00 to 23:59).
Statuses update automatically based on current time.
Resets at midnight with fresh day's schedule.

Usage:
  1. Manual once:   python flight_publisher.py
  2. Daily auto:    python flight_publisher.py --daily
  3. As API:        uvicorn flight_publisher:app --port 8001
"""

import os
import json
import time
import random
import argparse
import requests
import pika
from datetime import datetime, timedelta
from dotenv import load_dotenv

try:
    from fastapi import FastAPI, HTTPException, BackgroundTasks
    from fastapi.middleware.cors import CORSMiddleware
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

load_dotenv()

AVIATIONSTACK_KEY = os.getenv("AVIATIONSTACK_KEY", "1a7d8a5e7f3bcbce8f1e0f9eaf564f60")
AVIATIONSTACK_URL = "http://api.aviationstack.com/v1/flights"
RABBITMQ_HOST     = os.getenv("RABBITMQ_HOST", "localhost")
EXCHANGE_NAME     = "flights.morning"
QUEUE_NAME        = "morning_flights_queue"
ROUTING_KEY       = "flight.morning.data"

AIRPORTS = [
    {"iata": "DEL",  "airport_id": 1, "city": "Delhi"},
    {"iata": "BOM",  "airport_id": 2, "city": "Mumbai"},
    {"iata": "BOM",  "airport_id": 3, "city": "Navi Mumbai"},
    {"iata": "BLR",  "airport_id": 4, "city": "Bangalore"},
    {"iata": "HYD",  "airport_id": 5, "city": "Hyderabad"},
]

SUPPORTED_AIRLINES = {"6E", "QP", "EK", "AI", "UK"}

TERMINAL_MAP = {
    ("6E", False): "T1", ("6E", True): "T1",
    ("QP", False): "T1", ("QP", True): "T1",
    ("AI", False): "T2", ("AI", True): "T3",
    ("UK", False): "T2", ("UK", True): "T2",
    ("EK", False): "T3", ("EK", True): "T3",
}

GATE_RANGES = {
    "T1": (1,  20),
    "T2": (21, 40),
    "T3": (41, 60),
}

INTERNATIONAL_KEYWORDS = [
    "DXB", "LHR", "JFK", "SIN", "NRT", "CDG", "FRA",
    "AMS", "DOH", "KUL", "BKK", "SYD", "LAX", "YYZ",
    "Dubai", "London", "New York", "Singapore", "Tokyo",
    "Paris", "Amsterdam", "Doha", "Kuala Lumpur", "Bangkok",
]

# Real daily routes per airline (origin, destination, flight duration in minutes)
KNOWN_ROUTES = {
    "6E": [
        # DEL departures
        ("Delhi (DEL)",       "Mumbai (BOM)",       130),
        ("Delhi (DEL)",       "Bengaluru (BLR)",    170),
        ("Delhi (DEL)",       "Hyderabad (HYD)",    155),
        ("Delhi (DEL)",       "Chennai (MAA)",      165),
        ("Delhi (DEL)",       "Kolkata (CCU)",      150),
        ("Delhi (DEL)",       "Goa (GOI)",          165),
        ("Delhi (DEL)",       "Pune (PNQ)",         140),
        ("Delhi (DEL)",       "Ahmedabad (AMD)",    100),
        ("Delhi (DEL)",       "Jaipur (JAI)",        65),
        ("Delhi (DEL)",       "Lucknow (LKO)",       70),
        # BOM departures
        ("Mumbai (BOM)",      "Delhi (DEL)",        135),
        ("Mumbai (BOM)",      "Bengaluru (BLR)",    100),
        ("Mumbai (BOM)",      "Hyderabad (HYD)",     90),
        ("Mumbai (BOM)",      "Chennai (MAA)",       110),
        ("Mumbai (BOM)",      "Kolkata (CCU)",       155),
        ("Mumbai (BOM)",      "Goa (GOI)",            75),
        ("Mumbai (BOM)",      "Ahmedabad (AMD)",      65),
        ("Mumbai (BOM)",      "Jaipur (JAI)",        115),
        ("Mumbai (BOM)",      "Kochi (COK)",         120),
        ("Mumbai (BOM)",      "Pune (PNQ)",           30),
        # BLR departures
        ("Bengaluru (BLR)",   "Delhi (DEL)",        165),
        ("Bengaluru (BLR)",   "Mumbai (BOM)",       100),
        ("Bengaluru (BLR)",   "Hyderabad (HYD)",     60),
        ("Bengaluru (BLR)",   "Chennai (MAA)",        55),
        ("Bengaluru (BLR)",   "Kolkata (CCU)",       155),
        ("Bengaluru (BLR)",   "Goa (GOI)",            60),
        ("Bengaluru (BLR)",   "Kochi (COK)",          75),
        # HYD departures
        ("Hyderabad (HYD)",   "Delhi (DEL)",        155),
        ("Hyderabad (HYD)",   "Mumbai (BOM)",        90),
        ("Hyderabad (HYD)",   "Bengaluru (BLR)",     60),
        ("Hyderabad (HYD)",   "Chennai (MAA)",        70),
        ("Hyderabad (HYD)",   "Kolkata (CCU)",       145),
        ("Hyderabad (HYD)",   "Goa (GOI)",            80),
    ],
    "QP": [
        # DEL departures
        ("Delhi (DEL)",       "Mumbai (BOM)",       130),
        ("Delhi (DEL)",       "Bengaluru (BLR)",    165),
        ("Delhi (DEL)",       "Hyderabad (HYD)",    155),
        ("Delhi (DEL)",       "Ahmedabad (AMD)",    100),
        ("Delhi (DEL)",       "Goa (GOI)",          165),
        # BOM departures
        ("Mumbai (BOM)",      "Delhi (DEL)",        135),
        ("Mumbai (BOM)",      "Bengaluru (BLR)",    100),
        ("Mumbai (BOM)",      "Hyderabad (HYD)",     90),
        ("Mumbai (BOM)",      "Ahmedabad (AMD)",     65),
        ("Mumbai (BOM)",      "Goa (GOI)",           75),
        ("Mumbai (BOM)",      "Kochi (COK)",        120),
        # BLR departures
        ("Bengaluru (BLR)",   "Mumbai (BOM)",       100),
        ("Bengaluru (BLR)",   "Delhi (DEL)",        165),
        ("Bengaluru (BLR)",   "Hyderabad (HYD)",     60),
        ("Bengaluru (BLR)",   "Goa (GOI)",           60),
        # HYD departures
        ("Hyderabad (HYD)",   "Delhi (DEL)",        160),
        ("Hyderabad (HYD)",   "Mumbai (BOM)",        90),
        ("Hyderabad (HYD)",   "Bengaluru (BLR)",     60),
    ],
    "EK": [
        # International → India
        ("Dubai (DXB)",       "Delhi (DEL)",        195),
        ("Dubai (DXB)",       "Mumbai (BOM)",       195),
        ("Dubai (DXB)",       "Bengaluru (BLR)",    225),
        ("Dubai (DXB)",       "Hyderabad (HYD)",    210),
        ("London (LHR)",      "Delhi (DEL)",        510),
        ("London (LHR)",      "Mumbai (BOM)",       510),
        ("Singapore (SIN)",   "Mumbai (BOM)",       330),
        # India → International
        ("Delhi (DEL)",       "Dubai (DXB)",        195),
        ("Mumbai (BOM)",      "Dubai (DXB)",        195),
        ("Bengaluru (BLR)",   "Dubai (DXB)",        225),
        ("Hyderabad (HYD)",   "Dubai (DXB)",        210),
        ("Delhi (DEL)",       "London (LHR)",       510),
        ("Mumbai (BOM)",      "London (LHR)",       510),
        ("Mumbai (BOM)",      "Singapore (SIN)",    330),
    ],
    "AI": [
        # DEL departures
        ("Delhi (DEL)",       "Mumbai (BOM)",       130),
        ("Delhi (DEL)",       "Bengaluru (BLR)",    165),
        ("Delhi (DEL)",       "Hyderabad (HYD)",    155),
        ("Delhi (DEL)",       "Chennai (MAA)",      165),
        ("Delhi (DEL)",       "Kolkata (CCU)",      150),
        ("Delhi (DEL)",       "Goa (GOI)",          165),
        ("Delhi (DEL)",       "Ahmedabad (AMD)",    100),
        ("Delhi (DEL)",       "London (LHR)",       510),
        ("Delhi (DEL)",       "Singapore (SIN)",    345),
        ("Delhi (DEL)",       "New York (JFK)",     840),
        # BOM departures
        ("Mumbai (BOM)",      "Delhi (DEL)",        130),
        ("Mumbai (BOM)",      "Bengaluru (BLR)",    100),
        ("Mumbai (BOM)",      "Hyderabad (HYD)",     90),
        ("Mumbai (BOM)",      "Chennai (MAA)",       110),
        ("Mumbai (BOM)",      "Kolkata (CCU)",       155),
        ("Mumbai (BOM)",      "London (LHR)",        510),
        ("Mumbai (BOM)",      "Frankfurt (FRA)",     480),
        # BLR departures
        ("Bengaluru (BLR)",   "Delhi (DEL)",        165),
        ("Bengaluru (BLR)",   "Mumbai (BOM)",       100),
        ("Bengaluru (BLR)",   "Hyderabad (HYD)",     60),
        ("Bengaluru (BLR)",   "Chennai (MAA)",        55),
        # HYD departures
        ("Hyderabad (HYD)",   "Delhi (DEL)",        155),
        ("Hyderabad (HYD)",   "Mumbai (BOM)",        90),
        ("Hyderabad (HYD)",   "Bengaluru (BLR)",     60),
        ("Hyderabad (HYD)",   "Chennai (MAA)",        70),
    ],
    "UK": [
        # DEL departures
        ("Delhi (DEL)",       "Mumbai (BOM)",       130),
        ("Delhi (DEL)",       "Bengaluru (BLR)",    165),
        ("Delhi (DEL)",       "Hyderabad (HYD)",    155),
        ("Delhi (DEL)",       "Chennai (MAA)",      165),
        ("Delhi (DEL)",       "Kolkata (CCU)",      150),
        ("Delhi (DEL)",       "Goa (GOI)",          165),
        ("Delhi (DEL)",       "Pune (PNQ)",         140),
        ("Delhi (DEL)",       "Ahmedabad (AMD)",    100),
        # BOM departures
        ("Mumbai (BOM)",      "Delhi (DEL)",        130),
        ("Mumbai (BOM)",      "Bengaluru (BLR)",    100),
        ("Mumbai (BOM)",      "Hyderabad (HYD)",     90),
        ("Mumbai (BOM)",      "Chennai (MAA)",       110),
        ("Mumbai (BOM)",      "Kolkata (CCU)",       155),
        ("Mumbai (BOM)",      "Goa (GOI)",            75),
        ("Mumbai (BOM)",      "Pune (PNQ)",           30),
        ("Mumbai (BOM)",      "Ahmedabad (AMD)",      65),
        # BLR departures
        ("Bengaluru (BLR)",   "Delhi (DEL)",        165),
        ("Bengaluru (BLR)",   "Mumbai (BOM)",       100),
        ("Bengaluru (BLR)",   "Hyderabad (HYD)",     60),
        ("Bengaluru (BLR)",   "Chennai (MAA)",        55),
        ("Bengaluru (BLR)",   "Kolkata (CCU)",       155),
        # HYD departures
        ("Hyderabad (HYD)",   "Delhi (DEL)",        155),
        ("Hyderabad (HYD)",   "Mumbai (BOM)",        90),
        ("Hyderabad (HYD)",   "Bengaluru (BLR)",     60),
        ("Hyderabad (HYD)",   "Chennai (MAA)",        70),
    ],
}
FLIGHT_PREFIXES = {
    "6E": ("6E", 100,  9999),
    "QP": ("QP", 1000, 1999),
    "EK": ("EK", 500,  599),
    "AI": ("AI", 100,  999),
    "UK": ("UK", 700,  999),
}


# ── Schedule Generator ─────────────────────────────────────────────

class DailyScheduleGenerator:
    """
    Generates a full day's realistic flight schedule.
    - Uses real routes (from AviationStack or known routes)
    - Spreads flights across 00:00-23:59 with morning/evening peaks
    - Computes live status based on current time
    - Same flight number every day (consistent), different timings
    - Resets completely at midnight
    """

    def __init__(self):
        self._today = datetime.now().date()

    def _is_international(self, origin: str) -> bool:
        return any(kw in origin for kw in INTERNATIONAL_KEYWORDS)

    def _get_terminal(self, airline_code: str, origin: str) -> str:
        is_intl = self._is_international(origin)
        return TERMINAL_MAP.get((airline_code, is_intl), "T1")

    def _get_gate(self, flight_number: str, terminal: str) -> str:
        low, high = GATE_RANGES.get(terminal, (1, 20))
        seed = abs(hash(f"{flight_number}{self._today}"))
        gate_num = (seed % (high - low + 1)) + low
        return f"G{gate_num}"

    def _get_status(self, dep_time: str, arr_time: str) -> str:
        # Get the current time to calculate live status dynamically
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        try:
            # Parse departure and arrival times using today's date
            dep_dt = datetime.strptime(f"{today_str} {dep_time}", "%Y-%m-%d %H:%M")
            arr_dt = datetime.strptime(f"{today_str} {arr_time}", "%Y-%m-%d %H:%M")
            
            # If arrival time is earlier than departure time, the flight lands the next day
            if arr_dt < dep_dt:
                arr_dt += timedelta(days=1)
        except Exception:
            return "Scheduled"

        # Calculate time difference in minutes from now until departure
        diff_dep = (dep_dt - now).total_seconds() / 60

        # Assign status based on the current time vs departure/arrival times
        if now > arr_dt:
            return "Arrived"      # Flight has already landed
        elif now > dep_dt:
            return "Departed"     # Flight has taken off but not yet landed
        elif -5 <= diff_dep <= 45:
            # Flight is departing very soon; assign randomly as Delayed or Boarding
            return "Delayed" if random.random() < 0.12 else "Boarding"
        else:
            return "Scheduled"    # Flight is still in the future

    def _make_flight_number(self, airline_code: str, route_idx: int, offset: int = 0) -> str:
        prefix, low, high = FLIGHT_PREFIXES[airline_code]
        seed = abs(hash(f"{airline_code}{route_idx}{offset}{self._today}"))
        num = (seed % (high - low)) + low
        return f"{prefix}{num}"

    def _build_time_slots(self) -> list:
        slots = []
        # 04:00-06:00 international arrivals
        for h in range(4, 6):
            for m in [0, 20, 45]:
                slots.append(f"{h:02d}:{m:02d}")
        # 06:00-10:00 morning peak
        for h in range(6, 10):
            for m in [0, 10, 20, 35, 50]:
                slots.append(f"{h:02d}:{m:02d}")
        # 10:00-15:00 midday
        for h in range(10, 15):
            for m in [0, 20, 45]:
                slots.append(f"{h:02d}:{m:02d}")
        # 15:00-21:00 evening peak
        for h in range(15, 21):
            for m in [0, 15, 30, 50]:
                slots.append(f"{h:02d}:{m:02d}")
        # 21:00-23:30 night
        for h in range(21, 24):
            for m in [0, 30]:
                slots.append(f"{h:02d}:{m:02d}")
        return slots

    def generate(self, airport_id: int, airport_iata: str) -> list:
        flights = []
        seen = set()

        # Build a consistent list of available time slots for the day
        slots = self._build_time_slots()

        # Shuffle the slots using a fixed seed (date + airport) 
        # This ensures the schedule is randomly distributed but remains exactly the same 
        # if this script is run multiple times on the same day.
        rng = random.Random(f"{self._today}{airport_id}")
        rng.shuffle(slots)

        slot_idx = 0
        used_slots = set()

        # Filter routes for this specific airport
        airport_routes = []
        for airline_code, routes in KNOWN_ROUTES.items():
            for idx, (origin, destination, duration) in enumerate(routes):
                if airport_iata in origin or airport_iata in destination:
                    airport_routes.append((airline_code, origin, destination, duration, idx))

        rng.shuffle(airport_routes)

        for (airline_code, origin, destination, duration, route_idx) in airport_routes:
            if slot_idx >= len(slots):
                break

            dep_time = slots[slot_idx]
            while dep_time in used_slots and slot_idx < len(slots) - 1:
                slot_idx += 1
                dep_time = slots[slot_idx]

            used_slots.add(dep_time)
            slot_idx += 1

            dep_dt  = datetime.strptime(f"2000-01-01 {dep_time}", "%Y-%m-%d %H:%M")
            arr_dt  = dep_dt + timedelta(minutes=duration)
            arr_time = arr_dt.strftime("%H:%M")

            # Determine flight type based on origin/destination
            if airport_iata in origin:
                flight_type = "departure"
                terminal_source = origin
            else:
                flight_type = "arrival"
                terminal_source = destination

            fn       = self._make_flight_number(airline_code, route_idx)
            terminal = self._get_terminal(airline_code, terminal_source)
            gate     = self._get_gate(fn, terminal)
            status   = self._get_status(dep_time, arr_time)

            key = f"{fn}-{airport_id}-{flight_type}"
            if key not in seen:
                seen.add(key)
                flights.append({
                    "flight_number":   fn,
                    "airline_code":    airline_code,
                    "airport_id":      airport_id,
                    "origin":          origin,
                    "destination":     destination,
                    "departure_time":  dep_time,
                    "arrival_time":    arr_time,
                    "gate_number":     gate,
                    "terminal_number": terminal,
                    "status":          status,
                    "flight_type":     flight_type,
                })

            # Also create the return leg
            dep_slot_dt  = dep_dt + timedelta(minutes=50)
            dep_dep_time = dep_slot_dt.strftime("%H:%M")
            dep_arr_dt   = dep_slot_dt + timedelta(minutes=duration)
            dep_arr_time = dep_arr_dt.strftime("%H:%M")

            return_type = "arrival" if flight_type == "departure" else "departure"
            return_term_source = destination if flight_type == "departure" else origin

            fn2     = self._make_flight_number(airline_code, route_idx, offset=500)
            term2   = self._get_terminal(airline_code, return_term_source)
            gate2   = self._get_gate(fn2, term2)
            status2 = self._get_status(dep_dep_time, dep_arr_time)

            key2 = f"{fn2}-{airport_id}-{return_type}"
            if key2 not in seen:
                seen.add(key2)
                flights.append({
                    "flight_number":   fn2,
                    "airline_code":    airline_code,
                    "airport_id":      airport_id,
                    "origin":          destination,
                    "destination":     origin,
                    "departure_time":  dep_dep_time,
                    "arrival_time":    dep_arr_time,
                    "gate_number":     gate2,
                    "terminal_number": term2,
                    "status":          status2,
                    "flight_type":     return_type,
                })

        print(f"[Schedule] {airport_iata} (id={airport_id}): {len(flights)} flights for {self._today}")
        return flights


# ── AviationStack Fetcher ──────────────────────────────────────────

class AviationStackFetcher:

    def __init__(self, api_key: str):
        self._key = api_key

    def ping(self, airport_iata: str) -> bool:
        params = {"access_key": self._key, "arr_iata": airport_iata, "limit": 1}
        try:
            resp = requests.get(AVIATIONSTACK_URL, params=params, timeout=10)
            data = resp.json()
            if "error" in data:
                print(f"[AviationStack] API error: {data['error'].get('info','')}")
                return False
            print(f"[AviationStack] API reachable — {len(data.get('data',[]))} flights returned")
            return True
        except Exception as e:
            print(f"[AviationStack] Unreachable: {e}")
            return False


# ── RabbitMQ Publisher ─────────────────────────────────────────────

class FlightPublisher:

    def __init__(self):
        self._connection = None
        self._channel = None

    def connect(self):
        self._connection = pika.BlockingConnection(
            pika.ConnectionParameters(host=RABBITMQ_HOST, heartbeat=600)
        )
        self._channel = self._connection.channel()
        self._channel.exchange_declare(exchange=EXCHANGE_NAME, exchange_type="direct", durable=True)
        self._channel.queue_declare(queue=QUEUE_NAME, durable=True)
        self._channel.queue_bind(queue=QUEUE_NAME, exchange=EXCHANGE_NAME, routing_key=ROUTING_KEY)
        print(f"[Publisher] Connected to RabbitMQ")

    def publish_batch(self, flights: list) -> int:
        """
        Publishes a list of flight dictionaries to the RabbitMQ exchange.
        Each flight is sent as a separate JSON message.
        """
        if not self._connection or self._connection.is_closed:
            try:
                self.connect()
            except Exception as e:
                print(f"[Publisher] Cannot connect: {e}")
                return 0

        if not self._channel:
            return 0

        published = 0
        for f in flights:
            try:
                self._channel.basic_publish(
                    exchange=EXCHANGE_NAME,
                    routing_key=ROUTING_KEY,
                    body=json.dumps(f),
                    properties=pika.BasicProperties(delivery_mode=2, content_type="application/json"),
                )
                published += 1
                airline_names = {"6E": "IndiGo", "QP": "Akasa Air", "EK": "Emirates", "AI": "Air India", "UK": "Vistara"}
                airline_name = airline_names.get(f['airline_code'], f['airline_code'])
                print(f"[+] {f['flight_number']:10} | {airline_name:10} | {f['flight_type']:9} | {f['terminal_number']} | {f['gate_number']:4} | {f['status']:10} | {f['departure_time']}")
            except Exception as e:
                print(f"[Publisher] Error: {e}")

        self.close()
        return published

    def close(self):
        try:
            if self._connection and not self._connection.is_closed:
                self._connection.close()
        except Exception:
            pass


# ── Orchestrator ───────────────────────────────────────────────────

class FlightDataOrchestrator:

    def __init__(self):
        self._last_run_date = None

    def run_once(self) -> dict:
        print(f"\n{'='*60}")
        print(f"[Orchestrator] Generating daily schedule — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}\n")

        generator = DailyScheduleGenerator()
        all_flights = []

        for airport in AIRPORTS:
            flights = generator.generate(airport["airport_id"], airport["iata"])
            all_flights.extend(flights)

        print(f"\n[Orchestrator] Total: {len(all_flights)} flights across {len(AIRPORTS)} airports")
        published = FlightPublisher().publish_batch(all_flights)
        self._last_run_date = datetime.now().date()

        summary = {
            "date":      str(self._last_run_date),
            "timestamp": datetime.now().isoformat(),
            "generated": len(all_flights),
            "published": published,
        }
        print(f"\n[Orchestrator] Done — {published} flights published to RabbitMQ")
        print(f"{'='*60}\n")
        return summary

    def run_daily(self):
        """Runs at startup and resets at midnight every day."""
        print(f"[Orchestrator] Daily mode — auto-resets at midnight")
        while True:
            try:
                today = datetime.now().date()
                if self._last_run_date != today:
                    print(f"[Orchestrator] New day: {today} — generating fresh schedule")
                    self.run_once()
                now = datetime.now()
                midnight = datetime.combine(today + timedelta(days=1), datetime.min.time())
                sleep_secs = (midnight - now).total_seconds()
                print(f"[Orchestrator] Next reset at midnight ({int(sleep_secs//3600)}h {int((sleep_secs%3600)//60)}m away)")
                time.sleep(min(sleep_secs + 5, 1800))
            except KeyboardInterrupt:
                print("\n[Orchestrator] Stopped.")
                break
            except Exception as e:
                print(f"[Orchestrator] Error: {e}")
                time.sleep(300)


# ── FastAPI ────────────────────────────────────────────────────────

if HAS_FASTAPI:
    app = FastAPI(
        title="Flight Data Publisher",
        description="Generates realistic daily flight schedules and publishes to RabbitMQ",
        version="2.0.0",
    )
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    _orch = FlightDataOrchestrator()

    @app.get("/")
    def root():
        return {
            "service": "Flight Data Publisher v2",
            "status":  "running",
            "date":    str(datetime.now().date()),
            "time":    datetime.now().strftime("%H:%M:%S"),
        }

    @app.get("/health")
    def health():
        return {"status": "ok", "timestamp": datetime.now().isoformat()}

    @app.post("/publish")
    def trigger_publish(background_tasks: BackgroundTasks):
        background_tasks.add_task(_orch.run_once)
        return {
            "message": "Generating today's full flight schedule for all 5 airports",
            "date":    str(datetime.now().date()),
            "note":    "Flights appear on board within seconds via RabbitMQ",
        }

    @app.post("/publish/{airport_iata}")
    def trigger_airport(airport_iata: str, background_tasks: BackgroundTasks):
        airport_iata = airport_iata.upper()
        matched = [a for a in AIRPORTS if a["iata"] == airport_iata]
        if not matched:
            raise HTTPException(404, f"Airport '{airport_iata}' not found")
        def _run():
            gen = DailyScheduleGenerator()
            flights = []
            for a in matched:
                flights.extend(gen.generate(a["airport_id"], a["iata"]))
            FlightPublisher().publish_batch(flights)
        background_tasks.add_task(_run)
        return {"message": f"Generating schedule for {airport_iata}"}


# ── CLI ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Flight Data Publisher v2")
    parser.add_argument("--daily",   action="store_true", help="Run daily mode (auto-resets at midnight)")
    parser.add_argument("--airport", type=str, default=None, help="Single airport IATA (e.g. DEL)")
    args = parser.parse_args()

    orch = FlightDataOrchestrator()

    if args.daily:
        orch.run_daily()
    elif args.airport:
        gen = DailyScheduleGenerator()
        matched = [a for a in AIRPORTS if a["iata"] == args.airport.upper()]
        if not matched:
            print(f"Airport '{args.airport}' not found")
        else:
            flights = []
            for a in matched:
                flights.extend(gen.generate(a["airport_id"], a["iata"]))
            FlightPublisher().publish_batch(flights)
    else:
        orch.run_once()