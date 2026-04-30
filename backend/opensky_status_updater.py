"""
opensky_status_updater.py — Real-Time Flight Status Updater
============================================================
Polls the OpenSky Network API every 60 seconds to fetch live
aircraft transponder data and updates matching flight statuses
in the MySQL database.

Status Logic:
  on_ground == True  → "Arrived"
  on_ground == False → "In Air"

Callsign Normalization (ICAO → IATA):
  AIC → AI   (Air India)
  IGO → 6E   (IndiGo)
  AXB → IX   (Air Asia India)

Usage:
    python opensky_status_updater.py

Architecture:
    OpenSky API → normalize callsign → match DB flight_number → update status
"""

import os
import sys
import time
import requests
from datetime import datetime
from dotenv import load_dotenv

# ── Path fix: allow imports from backend/ when run directly ───────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
load_dotenv()

# ── Settings ──────────────────────────────────────────────────────────────────
OPENSKY_URL      = "https://opensky-network.org/api/states/all"
OPENSKY_USERNAME = os.getenv("OPENSKY_USERNAME", "")
OPENSKY_PASSWORD = os.getenv("OPENSKY_PASSWORD", "")
POLL_INTERVAL    = 60          # seconds between each update cycle
REQUEST_TIMEOUT  = 30          # seconds before HTTP request times out

# ICAO airline prefix → IATA airline code used in our DB flight numbers
CALLSIGN_PREFIX_MAP = {
    "AIC": "AI",    # Air India      ICAO: AIC → IATA: AI
    "IGO": "6E",    # IndiGo         ICAO: IGO → IATA: 6E
    "AXB": "IX",    # Air Asia India ICAO: AXB → IATA: IX
    # Carriers that use same IATA/ICAO code (no translation needed)
    # "EK"  → Emirates    (ICAO EK,  IATA EK)
    # "AIC" already covered above
}

# Optional telemetry columns — update them only if they exist on the model
TELEMETRY_FIELDS = ("latitude", "longitude", "altitude", "velocity")


# ── Callsign Normalizer ───────────────────────────────────────────────────────

def normalize_callsign(raw: str) -> str | None:
    """
    Convert a raw OpenSky callsign to the flight_number format stored in DB.

    Steps:
      1. Strip whitespace (OpenSky pads callsigns to 8 chars)
      2. Translate known ICAO 3-letter prefixes → IATA 2-letter codes
      3. Return None if the callsign is empty after stripping

    Examples:
      "AIC  302" → "AI302"
      "IGO 2341" → "6E2341"
      "EK   512" → "EK512"
    """
    if not raw:
        return None

    callsign = raw.strip().replace(" ", "")
    if not callsign:
        return None

    # Try to match a known ICAO prefix (3 chars) at the start
    for icao_prefix, iata_code in CALLSIGN_PREFIX_MAP.items():
        if callsign.upper().startswith(icao_prefix):
            numeric_part = callsign[len(icao_prefix):]
            callsign = f"{iata_code}{numeric_part}"
            break

    return callsign


# ── OpenSky Fetcher ───────────────────────────────────────────────────────────

class OpenSkyFetcher:
    """
    Fetches live aircraft state vectors from the OpenSky Network REST API.

    OpenSky state vector index reference:
      [0]  icao24        transponder address
      [1]  callsign      flight number (padded to 8 chars)
      [2]  origin_country
      [3]  time_position
      [4]  last_contact
      [5]  longitude
      [6]  latitude
      [7]  baro_altitude (metres)
      [8]  on_ground     bool
      [9]  velocity      m/s
      [10] true_track    degrees
      [11] vertical_rate m/s
      [12] sensors
      [13] geo_altitude
      [14] squawk
      [15] spi
      [16] position_source
    """

    def __init__(self, username: str, password: str):
        self._auth = (username, password) if username and password else None
        if not self._auth:
            print("[OpenSky] ⚠  No credentials set — using anonymous access "
                  "(rate-limited to ~1 req/10s).")

    def fetch(self) -> list[dict]:
        """
        Call the OpenSky API and return a list of normalized aircraft dicts.
        Returns an empty list on error so the caller can handle gracefully.
        """
        try:
            print(f"[OpenSky] Fetching live aircraft data…")
            resp = requests.get(
                OPENSKY_URL,
                auth=self._auth,
                timeout=REQUEST_TIMEOUT,
            )

            if resp.status_code == 429:
                print("[OpenSky] ⚠  Rate-limited (HTTP 429). Will retry next cycle.")
                return []

            if resp.status_code == 401:
                print("[OpenSky] ❌ Authentication failed — check OPENSKY_USERNAME / OPENSKY_PASSWORD.")
                return []

            if not resp.ok:
                print(f"[OpenSky] ❌ HTTP {resp.status_code}: {resp.text[:200]}")
                return []

            data = resp.json()
            states = data.get("states") or []
            print(f"[OpenSky] ✅ Received {len(states)} aircraft states.")

            aircraft = []
            for state in states:
                callsign_raw = state[1]
                if not callsign_raw or not callsign_raw.strip():
                    continue  # Skip transponders with no callsign

                normalized = normalize_callsign(callsign_raw)
                if not normalized:
                    continue

                aircraft.append({
                    "flight_number": normalized,
                    "on_ground":     state[8],
                    "latitude":      state[6],
                    "longitude":     state[5],
                    "altitude":      state[7],
                    "velocity":      state[9],
                })

            return aircraft

        except requests.exceptions.Timeout:
            print(f"[OpenSky] ❌ Request timed out after {REQUEST_TIMEOUT}s.")
            return []
        except requests.exceptions.ConnectionError as e:
            print(f"[OpenSky] ❌ Connection error: {e}")
            return []
        except Exception as e:
            print(f"[OpenSky] ❌ Unexpected fetch error: {e}")
            return []


# ── DB Updater ────────────────────────────────────────────────────────────────

class FlightStatusUpdater:
    """
    Matches OpenSky aircraft to flights in the MySQL database and updates
    their status (and optional telemetry fields) using SQLAlchemy sessions.
    """

    def __init__(self):
        # Import here so the module can be run standalone from backend/
        from core.database import DatabaseManager
        from models.models import FlightModel

        self._db      = DatabaseManager()
        self._Flight  = FlightModel

        # Detect whether optional telemetry columns exist on the ORM model
        self._has_telemetry = all(
            hasattr(self._Flight, col) for col in TELEMETRY_FIELDS
        )
        if self._has_telemetry:
            print("[Updater] Telemetry columns detected — latitude/longitude/"
                  "altitude/velocity will be updated.")
        else:
            print("[Updater] No telemetry columns on FlightModel — "
                  "only status will be updated.")

    @staticmethod
    def _resolve_status(on_ground: bool | None) -> str:
        """
        Map OpenSky on_ground flag → our DB status string.
        None (no data) is treated as airborne.
        """
        if on_ground is True:
            return "Arrived"
        return "In Air"

    def update(self, aircraft: list[dict]) -> int:
        """
        For each aircraft, look up matching flight(s) by flight_number and
        update their status (and telemetry if available).

        Returns the total count of DB rows updated.
        """
        if not aircraft:
            return 0

        # Build a lookup dict: flight_number → aircraft data
        # (a single callsign might match multiple DB rows for diff airports)
        lookup: dict[str, dict] = {}
        for a in aircraft:
            fn = a["flight_number"].upper()
            lookup[fn] = a   # last writer wins for same callsign

        updated_count = 0

        with self._db.session_scope() as session:
            for fn, ac in lookup.items():
                try:
                    # Match all DB flights with this flight_number
                    flights = (
                        session.query(self._Flight)
                        .filter(self._Flight.flight_number == fn)
                        .all()
                    )

                    if not flights:
                        continue

                    new_status = self._resolve_status(ac["on_ground"])

                    for flight in flights:
                        flight.status = new_status

                        if self._has_telemetry:
                            if ac["latitude"]  is not None:
                                flight.latitude  = ac["latitude"]
                            if ac["longitude"] is not None:
                                flight.longitude = ac["longitude"]
                            if ac["altitude"]  is not None:
                                flight.altitude  = ac["altitude"]
                            if ac["velocity"]  is not None:
                                flight.velocity  = ac["velocity"]

                        updated_count += 1

                except Exception as e:
                    print(f"[Updater] ⚠  Error updating flight {fn}: {e}")
                    # Continue updating remaining flights; session rolls back
                    # only if an unhandled exception propagates out of the
                    # session_scope context manager.

        return updated_count


# ── Main Loop ─────────────────────────────────────────────────────────────────

class OpenSkyStatusUpdaterService:
    """
    Orchestrates periodic fetching from OpenSky and DB updates.
    Runs forever in a while-True loop with a configurable sleep interval.
    All errors are caught to prevent the process from crashing.
    """

    def __init__(self):
        self._fetcher = OpenSkyFetcher(OPENSKY_USERNAME, OPENSKY_PASSWORD)
        self._updater = FlightStatusUpdater()

    def run_once(self) -> dict:
        """Execute one fetch-and-update cycle. Returns a result summary dict."""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n[Service] ── Cycle start: {ts} ──────────────────────────────")

        aircraft = self._fetcher.fetch()
        if not aircraft:
            print("[Service] No usable aircraft data — skipping DB update.")
            return {"timestamp": ts, "fetched": 0, "updated": 0}

        updated = self._updater.update(aircraft)
        print(f"[Service] ✅ Updated {updated} flight row(s) from "
              f"{len(aircraft)} aircraft callsigns.")

        return {"timestamp": ts, "fetched": len(aircraft), "updated": updated}

    def run(self):
        """
        Main blocking loop. Runs run_once() every POLL_INTERVAL seconds.
        Catches all exceptions so a transient error never kills the process.
        """
        print("=" * 62)
        print("  Beumer Group FMS — OpenSky Real-Time Status Updater")
        print(f"  Poll interval : {POLL_INTERVAL}s")
        print(f"  OpenSky user  : {OPENSKY_USERNAME or '(anonymous)'}")
        print("=" * 62)

        while True:
            try:
                self.run_once()
            except KeyboardInterrupt:
                print("\n[Service] Interrupted by user. Shutting down.")
                break
            except Exception as e:
                # Last-resort catch — log and keep running
                print(f"[Service] ❌ Unhandled error in cycle: {e}")

            print(f"[Service] Sleeping {POLL_INTERVAL}s until next cycle…\n")
            time.sleep(POLL_INTERVAL)


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    service = OpenSkyStatusUpdaterService()
    service.run()
