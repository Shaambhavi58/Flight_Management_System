"""
flight_publisher.py — Flight Data Publisher Library
=====================================================
Pure library module — imported by the main FastAPI backend (port 8000).
Generates today's FULL DAY schedule (00:00 to 23:59).
Statuses update automatically based on current time.

Sync Live endpoint: POST /flights/sync-live  →  app.py → flight_controller.py
                    This file is NOT run as a standalone server.

CLI (optional, for manual testing only):
  python flight_publisher.py           # publish once
  python flight_publisher.py --daily   # run daily loop
  python flight_publisher.py --airport DEL
"""

import os
import json
import time
import random
import argparse
import pika
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
EXCHANGE_NAME = "flights.morning"
QUEUE_NAME    = "morning_flights_queue"
ROUTING_KEY   = "flight.morning.data"

AIRPORTS = [
    {"iata": "DEL",  "airport_id": 1, "city": "Delhi"},
    {"iata": "BOM",  "airport_id": 2, "city": "Mumbai"},
    {"iata": "BOM",  "airport_id": 3, "city": "Navi Mumbai"},
    {"iata": "BLR",  "airport_id": 4, "city": "Bangalore"},
    {"iata": "HYD",  "airport_id": 5, "city": "Hyderabad"},
]

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
    - Spreads flights across 00:00-23:59 with morning/evening peaks.
    - Computes live status based on current time.
    - Same flight numbers every day (consistent seed), different timings.
    - Resets completely at midnight.
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
        """Compute live flight status based on current wall-clock time."""
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        try:
            dep_dt = datetime.strptime(f"{today_str} {dep_time}", "%Y-%m-%d %H:%M")
            arr_dt = datetime.strptime(f"{today_str} {arr_time}", "%Y-%m-%d %H:%M")
            # Handle overnight arrivals
            if arr_dt < dep_dt:
                arr_dt += timedelta(days=1)
        except Exception:
            return "Scheduled"

        diff_dep = (dep_dt - now).total_seconds() / 60

        if now > arr_dt:
            return "Arrived"
        elif now > dep_dt:
            return "Departed"
        elif -5 <= diff_dep <= 45:
            return "Delayed" if random.random() < 0.12 else "Boarding"
        else:
            return "Scheduled"

    def _make_flight_number(self, airline_code: str, route_idx: int, offset: int = 0) -> str:
        prefix, low, high = FLIGHT_PREFIXES[airline_code]
        seed = abs(hash(f"{airline_code}{route_idx}{offset}{self._today}"))
        num = (seed % (high - low)) + low
        return f"{prefix}{num}"

    def _build_time_slots(self) -> list:
        slots = []
        for h in range(4, 6):      # 04:00-06:00 international arrivals
            for m in [0, 20, 45]:
                slots.append(f"{h:02d}:{m:02d}")
        for h in range(6, 10):     # 06:00-10:00 morning peak
            for m in [0, 10, 20, 35, 50]:
                slots.append(f"{h:02d}:{m:02d}")
        for h in range(10, 15):    # 10:00-15:00 midday
            for m in [0, 20, 45]:
                slots.append(f"{h:02d}:{m:02d}")
        for h in range(15, 21):    # 15:00-21:00 evening peak
            for m in [0, 15, 30, 50]:
                slots.append(f"{h:02d}:{m:02d}")
        for h in range(21, 24):    # 21:00-23:30 night
            for m in [0, 30]:
                slots.append(f"{h:02d}:{m:02d}")
        return slots

    def generate(self, airport_id: int, airport_iata: str) -> list:
        """Generate all flights for one airport for today."""
        flights    = []
        seen       = set()
        seen_pairs: set = set()

        slots = self._build_time_slots()
        rng   = random.Random(f"{self._today}{airport_id}")
        rng.shuffle(slots)

        slot_idx   = 0
        used_slots = set()

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

            dep_dt   = datetime.strptime(f"2000-01-01 {dep_time}", "%Y-%m-%d %H:%M")
            arr_dt   = dep_dt + timedelta(minutes=duration)
            arr_time = arr_dt.strftime("%H:%M")

            if airport_iata in origin:
                flight_type     = "departure"
                terminal_source = origin
            else:
                flight_type     = "arrival"
                terminal_source = destination

            fn         = self._make_flight_number(airline_code, route_idx)
            terminal   = self._get_terminal(airline_code, terminal_source)
            gate       = self._get_gate(fn, terminal)
            status     = self._get_status(dep_time, arr_time)
            route_pair = frozenset({origin, destination})
            key        = f"{fn}-{airport_id}-{flight_type}"

            if key not in seen and route_pair not in seen_pairs:
                seen.add(key)
                seen_pairs.add(route_pair)
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

        return flights


# ── RabbitMQ Publisher ─────────────────────────────────────────────

class FlightPublisher:
    """Connects to RabbitMQ and publishes flight dicts as durable JSON messages."""

    def __init__(self):
        self._connection = None
        self._channel    = None

    def connect(self):
        self._connection = pika.BlockingConnection(
            pika.ConnectionParameters(host=RABBITMQ_HOST, heartbeat=600)
        )
        self._channel = self._connection.channel()
        self._channel.exchange_declare(exchange=EXCHANGE_NAME, exchange_type="direct", durable=True)
        self._channel.queue_declare(queue=QUEUE_NAME, durable=True)
        self._channel.queue_bind(queue=QUEUE_NAME, exchange=EXCHANGE_NAME, routing_key=ROUTING_KEY)

    def publish_batch(self, flights: list) -> int:
        """
        Publish a list of flight dicts to RabbitMQ.
        Returns the number of messages successfully published.
        """
        if not self._connection or self._connection.is_closed:
            try:
                self.connect()
            except Exception as e:
                print(f"[Sync Live] RabbitMQ connection failed: {e}")
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
            except Exception as e:
                print(f"[Sync Live] Publish error for {f.get('flight_number', '?')}: {e}")

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
    """
    Coordinates schedule generation + RabbitMQ publishing for all airports.
    Triggered by POST /flights/sync-live on the main backend.
    """

    def __init__(self):
        self._last_run_date = None

    def run_once(self, triggered_by: str = "system") -> dict:
        """
        Generate today's full flight schedule and publish to RabbitMQ.
        Emits structured [Sync Live] log lines for observability.

        Args:
            triggered_by: username of the admin who triggered the sync (for logs).

        Returns:
            Summary dict with date, counts, and execution time.
        """
        start_time = time.monotonic()
        today      = datetime.now()

        print(f"\n{'='*60}")
        print(f"[Sync Live] Started by {triggered_by} — {today.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}")

        generator       = DailyScheduleGenerator()
        publisher       = FlightPublisher()
        all_flights     = []
        airport_summary = {}   # iata → count published

        # Connect once for the whole batch
        try:
            publisher.connect()
            print(f"[Sync Live] RabbitMQ connected")
        except Exception as e:
            print(f"[Sync Live] RabbitMQ connection failed — aborting: {e}")
            return {"error": str(e), "published": 0}

        # Generate + publish per airport, tracking counts
        for airport in AIRPORTS:
            iata       = airport["iata"]
            airport_id = airport["airport_id"]
            city       = airport["city"]

            flights = generator.generate(airport_id, iata)
            count   = 0

            for f in flights:
                try:
                    publisher._channel.basic_publish(
                        exchange=EXCHANGE_NAME,
                        routing_key=ROUTING_KEY,
                        body=json.dumps(f),
                        properties=pika.BasicProperties(delivery_mode=2, content_type="application/json"),
                    )
                    count += 1
                except Exception as e:
                    print(f"[Sync Live] Error publishing {f.get('flight_number', '?')}: {e}")

            all_flights.extend(flights)
            airport_summary[iata] = count
            print(f"[Sync Live] {iata} ({city}) → {count} flights published")

        publisher.close()

        total_published = sum(airport_summary.values())
        elapsed_ms      = int((time.monotonic() - start_time) * 1000)
        self._last_run_date = today.date()

        print(f"[Sync Live] Total published: {total_published} flights across {len(AIRPORTS)} airports")
        print(f"[Sync Live] Completed successfully in {elapsed_ms}ms")
        print(f"{'='*60}\n")

        return {
            "date":       str(self._last_run_date),
            "timestamp":  today.isoformat(),
            "generated":  len(all_flights),
            "published":  total_published,
            "by_airport": airport_summary,
            "elapsed_ms": elapsed_ms,
            "triggered_by": triggered_by,
        }

    def run_daily(self):
        """Runs at startup and resets at midnight every day (CLI --daily mode)."""
        print(f"[Sync Live] Daily mode — auto-resets at midnight")
        while True:
            try:
                today = datetime.now().date()
                if self._last_run_date != today:
                    print(f"[Sync Live] New day: {today} — generating fresh schedule")
                    self.run_once(triggered_by="daily-scheduler")
                now      = datetime.now()
                midnight = datetime.combine(today + timedelta(days=1), datetime.min.time())
                sleep_secs = (midnight - now).total_seconds()
                print(f"[Sync Live] Next reset at midnight "
                      f"({int(sleep_secs // 3600)}h {int((sleep_secs % 3600) // 60)}m away)")
                time.sleep(min(sleep_secs + 5, 1800))
            except KeyboardInterrupt:
                print("\n[Sync Live] Daily mode stopped.")
                break
            except Exception as e:
                print(f"[Sync Live] Error in daily loop: {e}")
                time.sleep(300)


# ── CLI (manual testing only) ──────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Flight Data Publisher — CLI for manual testing",
        epilog="For Sync Live via UI, use POST /flights/sync-live on the main backend."
    )
    parser.add_argument("--daily",   action="store_true", help="Run daily mode (auto-resets at midnight)")
    parser.add_argument("--airport", type=str, default=None, help="Publish for a single airport IATA (e.g. DEL)")
    args = parser.parse_args()

    orch = FlightDataOrchestrator()

    if args.daily:
        orch.run_daily()
    elif args.airport:
        iata    = args.airport.upper()
        matched = [a for a in AIRPORTS if a["iata"] == iata]
        if not matched:
            print(f"[CLI] Airport '{iata}' not found. Available: {[a['iata'] for a in AIRPORTS]}")
        else:
            gen   = DailyScheduleGenerator()
            pub   = FlightPublisher()
            pub.connect()
            total = 0
            for a in matched:
                flights = gen.generate(a["airport_id"], a["iata"])
                for f in flights:
                    pub._channel.basic_publish(
                        exchange=EXCHANGE_NAME,
                        routing_key=ROUTING_KEY,
                        body=json.dumps(f),
                        properties=pika.BasicProperties(delivery_mode=2, content_type="application/json"),
                    )
                    total += 1
            pub.close()
            print(f"[CLI] Published {total} flights for {iata}")
    else:
        orch.run_once(triggered_by="cli")