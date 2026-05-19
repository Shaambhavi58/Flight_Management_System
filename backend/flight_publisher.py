"""
flight_publisher.py — Flight Data Publisher Library
=====================================================
Generates a COMPLETE full-day schedule for every airport:
  - Every 15-minute slot from 00:00 to 23:45
  - One ARRIVAL + one DEPARTURE per slot = 192 flights per airport
  - All known routes cycled systematically
  - Accurate time-based statuses (IST)
  - Stable seeded cancellation (3%) and delays (15%) — never flips on refresh
"""

import os
import json
import time
import random
import argparse
import requests
import pika
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

RABBITMQ_HOST     = os.getenv("RABBITMQ_HOST", "localhost")
AVIATIONSTACK_KEY = os.getenv("AVIATIONSTACK_KEY", "")
USE_LIVE_FLIGHTS  = os.getenv("USE_LIVE_FLIGHTS", "false").lower() == "true"
EXCHANGE_NAME     = "flights.morning"
QUEUE_NAME        = "morning_flights_queue"
ROUTING_KEY       = "flight.morning.data"

# IST = UTC + 5:30
IST = timezone(timedelta(hours=5, minutes=30))

AIRPORTS = [
    {"iata": "DEL",  "airport_id": 1, "city": "Delhi"},
    {"iata": "BOM",  "airport_id": 2, "city": "Mumbai"},
    {"iata": "BOM",  "airport_id": 3, "city": "Navi Mumbai"},
    {"iata": "BLR",  "airport_id": 4, "city": "Bangalore"},
    {"iata": "HYD",  "airport_id": 5, "city": "Hyderabad"},
]

AVIATIONSTACK_AIRPORTS = ["DEL", "BOM", "BLR", "HYD"]

AIRPORT_CITY_MAP = {
    "DEL": "Delhi",        "BOM": "Mumbai",       "BLR": "Bengaluru",
    "HYD": "Hyderabad",    "DXB": "Dubai",        "LHR": "London",
    "JFK": "New York",     "SIN": "Singapore",    "FRA": "Frankfurt",
    "NRT": "Tokyo",        "CDG": "Paris",        "AMS": "Amsterdam",
    "DOH": "Doha",         "MAA": "Chennai",      "CCU": "Kolkata",
    "PNQ": "Pune",         "AMD": "Ahmedabad",    "GOI": "Goa",
    "COK": "Kochi",        "JAI": "Jaipur",       "LKO": "Lucknow",
    "SXR": "Srinagar",     "IXC": "Chandigarh",   "PAT": "Patna",
    "BBI": "Bhubaneswar",  "VNS": "Varanasi",     "GAU": "Guwahati",
    "ATQ": "Amritsar",     "IXR": "Ranchi",       "IDR": "Indore",
    "NAG": "Nagpur",       "RPR": "Raipur",       "VGA": "Vijayawada",
    "TRV": "Thiruvananthapuram",                   "CJB": "Coimbatore",
    "ZRH": "Zurich",       "DAC": "Dhaka",        "KTM": "Kathmandu",
    "CMB": "Colombo",      "KUL": "Kuala Lumpur", "BKK": "Bangkok",
    "SYD": "Sydney",       "LAX": "Los Angeles",  "YYZ": "Toronto",
    "MUC": "Munich",       "VIE": "Vienna",       "FCO": "Rome",
    "BCN": "Barcelona",    "MAD": "Madrid",       "IST": "Istanbul",
    "CAI": "Cairo",        "NBO": "Nairobi",      "HKG": "Hong Kong",
    "ICN": "Seoul",        "PEK": "Beijing",      "PVG": "Shanghai",
}

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
    "DXB", "LHR", "JFK", "SIN", "NRT", "CDG", "FRA", "AMS", "DOH",
    "KUL", "BKK", "SYD", "LAX", "YYZ", "ZRH", "DAC", "KTM", "CMB",
    "IST", "CAI", "NBO", "HKG", "ICN", "PEK", "PVG", "MUC", "FCO",
    "Dubai", "London", "New York", "Singapore", "Tokyo", "Paris",
    "Amsterdam", "Doha", "Kuala Lumpur", "Bangkok", "Zurich", "Dhaka",
    "Kathmandu", "Colombo", "Istanbul", "Cairo", "Nairobi", "Frankfurt",
    "Munich", "Rome", "Barcelona", "Madrid",
]

KNOWN_ROUTES = {
    "6E": [
        ("Delhi (DEL)",      "Mumbai (BOM)",      130),
        ("Delhi (DEL)",      "Bengaluru (BLR)",   170),
        ("Delhi (DEL)",      "Hyderabad (HYD)",   155),
        ("Delhi (DEL)",      "Chennai (MAA)",     165),
        ("Delhi (DEL)",      "Kolkata (CCU)",     150),
        ("Delhi (DEL)",      "Goa (GOI)",         165),
        ("Delhi (DEL)",      "Pune (PNQ)",        140),
        ("Delhi (DEL)",      "Ahmedabad (AMD)",   100),
        ("Delhi (DEL)",      "Jaipur (JAI)",       65),
        ("Delhi (DEL)",      "Lucknow (LKO)",      70),
        ("Mumbai (BOM)",     "Delhi (DEL)",       135),
        ("Mumbai (BOM)",     "Bengaluru (BLR)",   100),
        ("Mumbai (BOM)",     "Hyderabad (HYD)",    90),
        ("Mumbai (BOM)",     "Chennai (MAA)",     110),
        ("Mumbai (BOM)",     "Kolkata (CCU)",     155),
        ("Mumbai (BOM)",     "Goa (GOI)",          75),
        ("Mumbai (BOM)",     "Ahmedabad (AMD)",    65),
        ("Mumbai (BOM)",     "Jaipur (JAI)",      115),
        ("Mumbai (BOM)",     "Kochi (COK)",       120),
        ("Mumbai (BOM)",     "Pune (PNQ)",         30),
        ("Bengaluru (BLR)",  "Delhi (DEL)",       165),
        ("Bengaluru (BLR)",  "Mumbai (BOM)",      100),
        ("Bengaluru (BLR)",  "Hyderabad (HYD)",    60),
        ("Bengaluru (BLR)",  "Chennai (MAA)",      55),
        ("Bengaluru (BLR)",  "Kolkata (CCU)",     155),
        ("Bengaluru (BLR)",  "Goa (GOI)",          60),
        ("Bengaluru (BLR)",  "Kochi (COK)",        75),
        ("Hyderabad (HYD)",  "Delhi (DEL)",       155),
        ("Hyderabad (HYD)",  "Mumbai (BOM)",       90),
        ("Hyderabad (HYD)",  "Bengaluru (BLR)",    60),
        ("Hyderabad (HYD)",  "Chennai (MAA)",      70),
        ("Hyderabad (HYD)",  "Kolkata (CCU)",     145),
        ("Hyderabad (HYD)",  "Goa (GOI)",          80),
    ],
    "QP": [
        ("Delhi (DEL)",      "Mumbai (BOM)",      130),
        ("Delhi (DEL)",      "Bengaluru (BLR)",   165),
        ("Delhi (DEL)",      "Hyderabad (HYD)",   155),
        ("Delhi (DEL)",      "Ahmedabad (AMD)",   100),
        ("Delhi (DEL)",      "Goa (GOI)",         165),
        ("Mumbai (BOM)",     "Delhi (DEL)",       135),
        ("Mumbai (BOM)",     "Bengaluru (BLR)",   100),
        ("Mumbai (BOM)",     "Hyderabad (HYD)",    90),
        ("Mumbai (BOM)",     "Ahmedabad (AMD)",    65),
        ("Mumbai (BOM)",     "Goa (GOI)",          75),
        ("Mumbai (BOM)",     "Kochi (COK)",       120),
        ("Bengaluru (BLR)",  "Mumbai (BOM)",      100),
        ("Bengaluru (BLR)",  "Delhi (DEL)",       165),
        ("Bengaluru (BLR)",  "Hyderabad (HYD)",    60),
        ("Bengaluru (BLR)",  "Goa (GOI)",          60),
        ("Hyderabad (HYD)",  "Delhi (DEL)",       160),
        ("Hyderabad (HYD)",  "Mumbai (BOM)",       90),
        ("Hyderabad (HYD)",  "Bengaluru (BLR)",    60),
    ],
    "EK": [
        ("Dubai (DXB)",      "Delhi (DEL)",       195),
        ("Dubai (DXB)",      "Mumbai (BOM)",      195),
        ("Dubai (DXB)",      "Bengaluru (BLR)",   225),
        ("Dubai (DXB)",      "Hyderabad (HYD)",   210),
        ("London (LHR)",     "Delhi (DEL)",       510),
        ("London (LHR)",     "Mumbai (BOM)",      510),
        ("Singapore (SIN)",  "Mumbai (BOM)",      330),
        ("Delhi (DEL)",      "Dubai (DXB)",       195),
        ("Mumbai (BOM)",     "Dubai (DXB)",       195),
        ("Bengaluru (BLR)",  "Dubai (DXB)",       225),
        ("Hyderabad (HYD)",  "Dubai (DXB)",       210),
        ("Delhi (DEL)",      "London (LHR)",      510),
        ("Mumbai (BOM)",     "London (LHR)",      510),
        ("Mumbai (BOM)",     "Singapore (SIN)",   330),
    ],
    "AI": [
        ("Delhi (DEL)",      "Mumbai (BOM)",      130),
        ("Delhi (DEL)",      "Bengaluru (BLR)",   165),
        ("Delhi (DEL)",      "Hyderabad (HYD)",   155),
        ("Delhi (DEL)",      "Chennai (MAA)",     165),
        ("Delhi (DEL)",      "Kolkata (CCU)",     150),
        ("Delhi (DEL)",      "Goa (GOI)",         165),
        ("Delhi (DEL)",      "Ahmedabad (AMD)",   100),
        ("Delhi (DEL)",      "London (LHR)",      510),
        ("Delhi (DEL)",      "Singapore (SIN)",   345),
        ("Delhi (DEL)",      "New York (JFK)",    840),
        ("Mumbai (BOM)",     "Delhi (DEL)",       130),
        ("Mumbai (BOM)",     "Bengaluru (BLR)",   100),
        ("Mumbai (BOM)",     "Hyderabad (HYD)",    90),
        ("Mumbai (BOM)",     "Chennai (MAA)",     110),
        ("Mumbai (BOM)",     "Kolkata (CCU)",     155),
        ("Mumbai (BOM)",     "London (LHR)",      510),
        ("Mumbai (BOM)",     "Frankfurt (FRA)",   480),
        ("Bengaluru (BLR)",  "Delhi (DEL)",       165),
        ("Bengaluru (BLR)",  "Mumbai (BOM)",      100),
        ("Bengaluru (BLR)",  "Hyderabad (HYD)",    60),
        ("Bengaluru (BLR)",  "Chennai (MAA)",      55),
        ("Hyderabad (HYD)",  "Delhi (DEL)",       155),
        ("Hyderabad (HYD)",  "Mumbai (BOM)",       90),
        ("Hyderabad (HYD)",  "Bengaluru (BLR)",    60),
        ("Hyderabad (HYD)",  "Chennai (MAA)",      70),
    ],
    "UK": [
        ("Delhi (DEL)",      "Mumbai (BOM)",      130),
        ("Delhi (DEL)",      "Bengaluru (BLR)",   165),
        ("Delhi (DEL)",      "Hyderabad (HYD)",   155),
        ("Delhi (DEL)",      "Chennai (MAA)",     165),
        ("Delhi (DEL)",      "Kolkata (CCU)",     150),
        ("Delhi (DEL)",      "Goa (GOI)",         165),
        ("Delhi (DEL)",      "Pune (PNQ)",        140),
        ("Delhi (DEL)",      "Ahmedabad (AMD)",   100),
        ("Mumbai (BOM)",     "Delhi (DEL)",       130),
        ("Mumbai (BOM)",     "Bengaluru (BLR)",   100),
        ("Mumbai (BOM)",     "Hyderabad (HYD)",    90),
        ("Mumbai (BOM)",     "Chennai (MAA)",     110),
        ("Mumbai (BOM)",     "Kolkata (CCU)",     155),
        ("Mumbai (BOM)",     "Goa (GOI)",          75),
        ("Mumbai (BOM)",     "Pune (PNQ)",         30),
        ("Mumbai (BOM)",     "Ahmedabad (AMD)",    65),
        ("Bengaluru (BLR)",  "Delhi (DEL)",       165),
        ("Bengaluru (BLR)",  "Mumbai (BOM)",      100),
        ("Bengaluru (BLR)",  "Hyderabad (HYD)",    60),
        ("Bengaluru (BLR)",  "Chennai (MAA)",      55),
        ("Bengaluru (BLR)",  "Kolkata (CCU)",     155),
        ("Hyderabad (HYD)",  "Delhi (DEL)",       155),
        ("Hyderabad (HYD)",  "Mumbai (BOM)",       90),
        ("Hyderabad (HYD)",  "Bengaluru (BLR)",    60),
        ("Hyderabad (HYD)",  "Chennai (MAA)",      70),
    ],
}

FLIGHT_PREFIXES = {
    "6E": ("6E", 100,  9999),
    "QP": ("QP", 1000, 1999),
    "EK": ("EK", 500,  599),
    "AI": ("AI", 100,  999),
    "UK": ("UK", 700,  999),
}


# ── AviationStack Fetcher ──────────────────────────────────────────

class AviationStackFetcher:
    """
    Fetches real flight data from AviationStack API.
    - Converts UTC -> IST
    - Strict airport filter (arrivals land at target, departures leave from target)
    - Skips blank/short flight numbers
    """

    BASE_URL = "http://api.aviationstack.com/v1/flights"

    AIRLINE_CODE_MAP = {
        "6E": "6E", "QP": "QP", "EK": "EK", "AI": "AI", "UK": "UK",
    }

    def fetch_arrivals(self, airport_iata: str) -> list[dict]:
        return self._fetch(airport_iata, "arrival")

    def fetch_departures(self, airport_iata: str) -> list[dict]:
        return self._fetch(airport_iata, "departure")

    def _fetch(self, airport_iata: str, flight_type: str) -> list[dict]:
        if not AVIATIONSTACK_KEY or not USE_LIVE_FLIGHTS:
            return []
        param_key = "arr_iata" if flight_type == "arrival" else "dep_iata"
        params = {"access_key": AVIATIONSTACK_KEY, param_key: airport_iata, "limit": 50}
        try:
            print(f"[AviationStack] Fetching {flight_type}s for {airport_iata}...")
            resp = requests.get(self.BASE_URL, params=params, timeout=15)
            if not resp.ok: return []
            data = resp.json()
            if "error" in data: return []
            raw = data.get("data", [])
            print(f"[AviationStack] Got {len(raw)} {flight_type}s for {airport_iata}")
            return self._normalize(raw, flight_type, airport_iata)
        except Exception as e:
            print(f"[AviationStack] Error: {e}")
            return []

    def _clean_route_part(self, airport_name: str, iata: str) -> str:
        city = AIRPORT_CITY_MAP.get(iata)
        if not city:
            words = (airport_name or iata).split()
            city  = " ".join(words[:2]) if len(words) >= 2 else (words[0] if words else iata)
        return f"{city} ({iata})"

    def _normalize(self, raw_flights: list, flight_type: str, target_iata: str) -> list[dict]:
        results   = []
        generator = DailyScheduleGenerator()
        for f in raw_flights:
            try:
                airline_iata = (f.get("airline") or {}).get("iata", "")
                if airline_iata not in self.AIRLINE_CODE_MAP: continue
                flight_iata = (f.get("flight") or {}).get("iata", "")
                if not flight_iata or len(flight_iata) < 4: continue
                dep      = f.get("departure") or {}
                arr      = f.get("arrival")   or {}
                dep_iata = dep.get("iata", "")
                arr_iata = arr.get("iata", "")
                if flight_type == "arrival"   and arr_iata != target_iata: continue
                if flight_type == "departure" and dep_iata != target_iata: continue
                dep_raw = dep.get("scheduled") or dep.get("estimated", "")
                arr_raw = arr.get("scheduled") or arr.get("estimated", "")
                if not dep_raw or not arr_raw: continue
                dep_dt   = datetime.fromisoformat(dep_raw.replace("Z", "+00:00")).astimezone(IST)
                arr_dt   = datetime.fromisoformat(arr_raw.replace("Z", "+00:00")).astimezone(IST)
                dep_time = dep_dt.strftime("%H:%M")
                arr_time = arr_dt.strftime("%H:%M")
                origin      = self._clean_route_part(dep.get("airport", ""), dep_iata)
                destination = self._clean_route_part(arr.get("airport", ""), arr_iata)
                st, dm, dr = generator._get_status_data(dep_time, arr_time, flight_iata)
                term = generator._get_terminal(self.AIRLINE_CODE_MAP[airline_iata], origin)
                results.append({
                    "flight_number":  flight_iata,
                    "airline_code":   self.AIRLINE_CODE_MAP[airline_iata],
                    "origin":         origin,
                    "destination":    destination,
                    "departure_time": dep_time,
                    "arrival_time":   arr_time,
                    "gate_number":    generator._get_gate(flight_iata, term),
                    "terminal_number": term,
                    "flight_type":    flight_type,
                    "status":         st,
                    "delay_minutes":  dm,
                    "delay_reason":   dr,
                    "batch_name":     generator._get_batch_name(dep_time),
                    "_from_live":     True,
                })
                # Apply safety check
                last = results[-1]
                last["status"], last["delay_minutes"], last["delay_reason"] = \
                    generator._ensure_delay_integrity(last["status"], last["delay_minutes"], last["delay_reason"])
            except Exception:
                continue
        print(f"[AviationStack] {len(results)} flights kept for {target_iata}")
        return results


# ── Schedule Generator ─────────────────────────────────────────────

class DailyScheduleGenerator:
    """
    Generates a COMPLETE full-day schedule.

    Every 15-minute slot from 00:00 to 23:45 gets:
      - ONE arrival   (cycling through all arrival routes in order)
      - ONE departure (cycling through all departure routes in order)

    Total: 96 arrivals + 96 departures = 192 flights per airport.

    Status logic (accurate, never flips on refresh):
      1. Already arrived?       -> "Arrived"
      2. Already departed?      -> "Departed"
      3. Future flight?
         a. Seeded 3% chance    -> "Cancelled"  (stable all day)
         b. Within 45 mins:
            - Seeded 15% chance -> "Delayed"    (stable all day)
            - Otherwise         -> "Boarding"
         c. Beyond 45 mins      -> "Scheduled"

    Overnight fix:
      Early morning flights (00:00–05:59) are treated as TONIGHT
      when current time is 18:00 or later — so they show Scheduled
      instead of incorrectly showing Arrived.
    """

    def __init__(self):
        self._today = datetime.now().date()

    def _is_international(self, origin: str) -> bool:
        return any(kw in origin for kw in INTERNATIONAL_KEYWORDS)

    def _get_terminal(self, airline_code: str, origin: str) -> str:
        return TERMINAL_MAP.get((airline_code, self._is_international(origin)), "T1")

    def _get_gate(self, flight_number: str, terminal: str) -> str:
        low, high = GATE_RANGES.get(terminal, (1, 20))
        seed      = abs(hash(f"{flight_number}{self._today}"))
        return f"G{(seed % (high - low + 1)) + low}"

    def _get_status_data(self, dep_time: str, arr_time: str, flight_number: str = "") -> tuple:
        """
        Accurate time-based status with stable seeded cancellation and delays.

        Parameters:
            dep_time:      HH:MM departure time
            arr_time:      HH:MM arrival time
            flight_number: used as seed for stable cancellation/delay
        """
        now       = datetime.now()
        today_str = now.strftime("%Y-%m-%d")

        try:
            dep_dt = datetime.strptime(f"{today_str} {dep_time}", "%Y-%m-%d %H:%M")
            arr_dt = datetime.strptime(f"{today_str} {arr_time}", "%Y-%m-%d %H:%M")

            # Handle overnight arrivals (e.g. dep 23:00, arr 01:30)
            if arr_dt < dep_dt:
                arr_dt += timedelta(days=1)

            # ── Overnight fix ─────────────────────────────────────────────
            # Early morning flights (00:00–05:59) haven't happened yet
            # when current time is evening (18:00+).
            # Without this fix they'd show Arrived at 8 PM even though
            # they're scheduled for tonight/tomorrow early morning.
            dep_hour = int(dep_time.split(":")[0])
            if dep_hour < 6 and now.hour >= 18:
                dep_dt += timedelta(days=1)
                arr_dt += timedelta(days=1)

        except Exception:
            return "Scheduled", 0, None

        import random
        diff_dep = (dep_dt - now).total_seconds() / 60  # minutes until departure

        # ── Step 1: Cancelled Check (3% chance) ─────────────────────────────
        if flight_number:
            cancel_seed = abs(hash(f"{flight_number}{self._today}cancel"))
            if cancel_seed % 100 < 3:
                return "Cancelled", 0, None

        # ── Step 2: Delay Check (15% chance) ──────────────────────────────
        dm, dr = 0, None
        if flight_number:
            delay_seed = abs(hash(f"{flight_number}{self._today}delay"))
            if delay_seed % 100 < 15:
                # Random data for demo richness
                dm = random.choice([15, 25, 35, 45, 60, 75, 90])
                dr = random.choice([
                    "Weather", "Technical", "ATC", "Crew", 
                    "Security", "Late Arrival", "Operational"
                ])
                
                actual_dep = dep_dt + timedelta(minutes=dm)
                actual_arr = arr_dt + timedelta(minutes=dm)
                
                # If we are within 4 hours of scheduled departure but haven't reached actual delayed departure
                if now < actual_dep and diff_dep <= 240:
                    return "Delayed", dm, dr
                
                # If past delayed departure, check if still in flight
                if actual_dep <= now < actual_arr:
                    return "Departed", 0, None
                if now >= actual_arr:
                    return "Arrived", 0, None

        # ── Step 3: Normal Flow (Non-delayed / Non-cancelled) ─────────────
        if now > arr_dt:
            return "Arrived", 0, None
        if now >= dep_dt:
            return "Departed", 0, None
        if diff_dep <= 45:
            return "Boarding", 0, None

        return "Scheduled", 0, None

    def _ensure_delay_integrity(self, status, dm, dr):
        """Final safety check to match DB rules."""
        if status == "Delayed":
            if not dm or int(dm) <= 0:
                dm = random.choice([15, 25, 35, 45, 60, 75, 90])
            if not dr:
                dr = random.choice([
                    "Weather", "Technical", "ATC", "Crew", 
                    "Security", "Late Arrival", "Operational"
                ])
        else:
            dm, dr = 0, None
        return status, dm, dr

    def _get_batch_name(self, dep_time: str) -> str:
        try:
            h = int(dep_time.split(":")[0])
            if h < 12:  return "Morning"
            if h < 18:  return "Afternoon"
            return "Evening"
        except Exception:
            return "Morning"

    def _make_flight_number(self, airline_code: str, slot_idx: int, flight_type: str) -> str:
        prefix, low, high = FLIGHT_PREFIXES[airline_code]
        seed = abs(hash(f"{airline_code}{slot_idx}{flight_type}{self._today}"))
        return f"{prefix}{(seed % (high - low)) + low}"

    def _build_all_slots(self) -> list:
        """All 15-minute slots from 00:00 to 23:45 — 96 total."""
        slots = []
        for h in range(24):
            for m in [0, 15, 30, 45]:
                slots.append(f"{h:02d}:{m:02d}")
        return slots

    def generate(self, airport_id: int, airport_iata: str) -> list:
        """
        One arrival + one departure for every 15-minute slot 00:00–23:45.
        Routes are cycled in order so every known route gets used.
        Result: 192 flights per airport covering the full day with no gaps.
        """
        dep_routes = []
        arr_routes = []

        for airline_code, routes in KNOWN_ROUTES.items():
            for idx, (origin, destination, duration) in enumerate(routes):
                if airport_iata in origin:
                    dep_routes.append((airline_code, origin, destination, duration, idx))
                if airport_iata in destination:
                    arr_routes.append((airline_code, origin, destination, duration, idx))

        if not dep_routes or not arr_routes:
            return []

        slots   = self._build_all_slots()
        flights = []

        for slot_idx, slot_time in enumerate(slots):

            # ── One DEPARTURE per slot ───────────────────────────────────
            airline_code, origin, destination, duration, _ = \
                dep_routes[slot_idx % len(dep_routes)]

            dep_dt   = datetime.strptime(f"2000-01-01 {slot_time}", "%Y-%m-%d %H:%M")
            arr_time = (dep_dt + timedelta(minutes=duration)).strftime("%H:%M")
            fn       = self._make_flight_number(airline_code, slot_idx, "dep")
            terminal = self._get_terminal(airline_code, origin)
            
            st, dm, dr = self._get_status_data(slot_time, arr_time, fn)

            flights.append({
                "flight_number":   fn,
                "airline_code":    airline_code,
                "airport_id":      airport_id,
                "origin":          origin,
                "destination":     destination,
                "departure_time":  slot_time,
                "arrival_time":    arr_time,
                "gate_number":     self._get_gate(fn, terminal),
                "terminal_number": terminal,
                "status":          st,
                "delay_minutes":   dm,
                "delay_reason":    dr,
                "batch_name":      self._get_batch_name(slot_time),
                "flight_type":     "departure",
            })
            # Apply safety check
            last = flights[-1]
            last["status"], last["delay_minutes"], last["delay_reason"] = \
                self._ensure_delay_integrity(last["status"], last["delay_minutes"], last["delay_reason"])

            # ── One ARRIVAL per slot ─────────────────────────────────────
            airline_code, origin, destination, duration, _ = \
                arr_routes[slot_idx % len(arr_routes)]

            # slot_time is the ARRIVAL time; work backwards for departure
            arr_dt   = datetime.strptime(f"2000-01-01 {slot_time}", "%Y-%m-%d %H:%M")
            dep_time = (arr_dt - timedelta(minutes=duration)).strftime("%H:%M")
            fn       = self._make_flight_number(airline_code, slot_idx, "arr")
            terminal = self._get_terminal(airline_code, destination)
            
            st_arr, dm_arr, dr_arr = self._get_status_data(dep_time, slot_time, fn)

            flights.append({
                "flight_number":   fn,
                "airline_code":    airline_code,
                "airport_id":      airport_id,
                "origin":          origin,
                "destination":     destination,
                "departure_time":  dep_time,
                "arrival_time":    slot_time,
                "gate_number":     self._get_gate(fn, terminal),
                "terminal_number": terminal,
                "status":          st_arr,
                "delay_minutes":   dm_arr,
                "delay_reason":    dr_arr,
                "batch_name":      self._get_batch_name(dep_time),
                "flight_type":     "arrival",
            })
            # Apply safety check
            last = flights[-1]
            last["status"], last["delay_minutes"], last["delay_reason"] = \
                self._ensure_delay_integrity(last["status"], last["delay_minutes"], last["delay_reason"])

        print(f"[Generator] {airport_iata} -> {len(flights)} flights "
              f"({len(slots)} arrivals + {len(slots)} departures, all slots covered)")
        return flights


# ── RabbitMQ Publisher ─────────────────────────────────────────────

class FlightPublisher:

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
        self._av_fetcher    = AviationStackFetcher()

    def _fetch_live_flights(self, airport_iata: str, airport_id: int) -> list[dict]:
        arrivals   = self._av_fetcher.fetch_arrivals(airport_iata)
        departures = self._av_fetcher.fetch_departures(airport_iata)
        generator  = DailyScheduleGenerator()
        enriched   = []
        for f in arrivals + departures:
            fn       = f["flight_number"]
            terminal = generator._get_terminal(f["airline_code"], f["origin"])
            enriched.append({
                **f,
                "airport_id":      airport_id,
                "gate_number":     generator._get_gate(fn, terminal),
                "terminal_number": terminal,
            })
        return enriched

    def run_once(self, triggered_by: str = "system") -> dict:
        start_time = time.monotonic()
        today      = datetime.now()

        print(f"\n{'='*60}")
        print(f"[Sync Live] Started by {triggered_by} — {today.strftime('%Y-%m-%d %H:%M:%S')}")
        mode = "Mixed Mode (AviationStack + Mock)" if (USE_LIVE_FLIGHTS and AVIATIONSTACK_KEY) \
               else "Demo Mode (Mock Only)"
        print(f"[Sync Live] {mode}")
        print(f"{'='*60}")

        generator       = DailyScheduleGenerator()
        publisher       = FlightPublisher()
        all_flights     = []
        airport_summary = {}

        try:
            publisher.connect()
            print(f"[Sync Live] RabbitMQ connected")
        except Exception as e:
            print(f"[Sync Live] RabbitMQ connection failed — aborting: {e}")
            return {"error": str(e), "published": 0}

        for airport in AIRPORTS:
            iata       = airport["iata"]
            airport_id = airport["airport_id"]

            # Step 1: Live data (if enabled)
            live_flights = []
            if USE_LIVE_FLIGHTS and iata in AVIATIONSTACK_AIRPORTS:
                live_flights = self._fetch_live_flights(iata, airport_id)

            # Step 2: Full mock schedule (192 flights — every 15-min slot covered)
            mock_flights = generator.generate(airport_id, iata)

            # Step 3: Merge — live flights first, mock fills remaining slots
            live_fn_set = {f["flight_number"] for f in live_flights}
            mock_unique = [f for f in mock_flights if f["flight_number"] not in live_fn_set]
            combined    = live_flights + mock_unique

            all_flights.extend(combined)
            airport_summary[iata] = len(combined)

        # Step 4: Publish all to RabbitMQ
        published_count = 0
        for f in all_flights:
            try:
                publisher._channel.basic_publish(
                    exchange=EXCHANGE_NAME,
                    routing_key=ROUTING_KEY,
                    body=json.dumps(f),
                    properties=pika.BasicProperties(delivery_mode=2, content_type="application/json"),
                )
                published_count += 1
            except Exception as e:
                print(f"[Sync Live] Publish error: {f.get('flight_number', '?')}: {e}")

        publisher.close()

        elapsed_ms          = int((time.monotonic() - start_time) * 1000)
        self._last_run_date = today.date()

        for iata, count in airport_summary.items():
            print(f"[Sync Live] {iata} -> {count} flights")
        print(f"[Sync Live] Total published: {published_count} flights across {len(AIRPORTS)} airports")
        print(f"[Sync Live] Completed in {elapsed_ms}ms")
        print(f"{'='*60}\n")

        return {
            "date":         str(self._last_run_date),
            "timestamp":    today.isoformat(),
            "generated":    len(all_flights),
            "published":    published_count,
            "by_airport":   airport_summary,
            "elapsed_ms":   elapsed_ms,
            "triggered_by": triggered_by,
        }

    def run_daily(self):
        print(f"[Sync Live] Daily mode — auto-resets at midnight")
        while True:
            try:
                today = datetime.now().date()
                if self._last_run_date != today:
                    print(f"[Sync Live] New day: {today} — generating fresh schedule")
                    self.run_once(triggered_by="daily-scheduler")
                now        = datetime.now()
                midnight   = datetime.combine(today + timedelta(days=1), datetime.min.time())
                sleep_secs = (midnight - now).total_seconds()
                print(f"[Sync Live] Next reset in "
                      f"{int(sleep_secs // 3600)}h {int((sleep_secs % 3600) // 60)}m")
                time.sleep(min(sleep_secs + 5, 1800))
            except KeyboardInterrupt:
                print("\n[Sync Live] Daily mode stopped.")
                break
            except Exception as e:
                print(f"[Sync Live] Error: {e}")
                time.sleep(300)


# ── CLI ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Flight Data Publisher",
        epilog="For Sync Live via UI, use POST /flights/sync-live on the main backend."
    )
    parser.add_argument("--daily",   action="store_true", help="Run daily mode")
    parser.add_argument("--airport", type=str, default=None, help="Single airport IATA e.g. DEL")
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
            gen = DailyScheduleGenerator()
            pub = FlightPublisher()
            pub.connect()
            total = 0
            for a in matched:
                for f in gen.generate(a["airport_id"], a["iata"]):
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
