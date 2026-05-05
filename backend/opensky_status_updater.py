"""
opensky_status_updater.py — Real-Time Flight Status Updater
============================================================
Polls the OpenSky Network API every 300 seconds to fetch live
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
    OpenSky API (OAuth2) → normalize callsign → match DB flight_number → update status
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
OPENSKY_URL       = "https://opensky-network.org/api/states/all"
OPENSKY_TOKEN_URL = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"

# OAuth2 credentials (from downloaded credentials.json)
OPENSKY_CLIENT_ID     = os.getenv("OPENSKY_CLIENT_ID", "")
OPENSKY_CLIENT_SECRET = os.getenv("OPENSKY_CLIENT_SECRET", "")

# Fallback: basic auth (legacy)
OPENSKY_USERNAME = os.getenv("OPENSKY_USERNAME", "")
OPENSKY_PASSWORD = os.getenv("OPENSKY_PASSWORD", "")

POLL_INTERVAL   = 300   # seconds between each update cycle
REQUEST_TIMEOUT = 30    # seconds before HTTP request times out

# ICAO airline prefix → IATA airline code used in our DB flight numbers
CALLSIGN_PREFIX_MAP = {
    "AIC": "AI",    # Air India      ICAO: AIC → IATA: AI
    "IGO": "6E",    # IndiGo         ICAO: IGO → IATA: 6E
    "AXB": "IX",    # Air Asia India ICAO: AXB → IATA: IX
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

    for icao_prefix, iata_code in CALLSIGN_PREFIX_MAP.items():
        if callsign.upper().startswith(icao_prefix):
            numeric_part = callsign[len(icao_prefix):]
            callsign = f"{iata_code}{numeric_part}"
            break

    return callsign


# ── OAuth2 Token Manager ──────────────────────────────────────────────────────

class OAuth2TokenManager:
    """
    Manages OAuth2 access token for OpenSky API.
    Automatically fetches a new token when expired.
    """

    def __init__(self, client_id: str, client_secret: str):
        self._client_id     = client_id
        self._client_secret = client_secret
        self._access_token  = None
        self._token_expiry  = 0

    def get_token(self) -> str | None:
        """Return a valid access token, refreshing if needed."""
        if self._access_token and time.time() < self._token_expiry - 30:
            return self._access_token  # still valid

        return self._fetch_token()

    def _fetch_token(self) -> str | None:
        """Fetch a new OAuth2 access token using client credentials flow."""
        try:
            print("[OAuth2] Fetching new access token…")
            resp = requests.post(
                OPENSKY_TOKEN_URL,
                data={
                    "grant_type":    "client_credentials",
                    "client_id":     self._client_id,
                    "client_secret": self._client_secret,
                },
                timeout=REQUEST_TIMEOUT,
            )

            if not resp.ok:
                print(f"[OAuth2] ❌ Token fetch failed — HTTP {resp.status_code}: {resp.text[:200]}")
                return None

            token_data = resp.json()
            self._access_token = token_data.get("access_token")
            expires_in         = token_data.get("expires_in", 300)
            self._token_expiry = time.time() + expires_in

            print(f"[OAuth2] ✅ Token acquired — expires in {expires_in}s")
            return self._access_token

        except Exception as e:
            print(f"[OAuth2] ❌ Token fetch error: {e}")
            return None


# ── OpenSky Fetcher ───────────────────────────────────────────────────────────

class OpenSkyFetcher:
    """
    Fetches live aircraft state vectors from the OpenSky Network REST API.
    Uses OAuth2 if client credentials are available, falls back to basic auth.

    OpenSky state vector index reference:
      [0]  icao24        transponder address
      [1]  callsign      flight number (padded to 8 chars)
      [5]  longitude
      [6]  latitude
      [7]  baro_altitude (metres)
      [8]  on_ground     bool
      [9]  velocity      m/s
    """

    def __init__(self):
        # Prefer OAuth2 over basic auth
        if OPENSKY_CLIENT_ID and OPENSKY_CLIENT_SECRET:
            self._token_manager = OAuth2TokenManager(
                OPENSKY_CLIENT_ID, OPENSKY_CLIENT_SECRET
            )
            self._use_oauth2 = True
            print("[OpenSky] Using OAuth2 authentication (client credentials)")
        elif OPENSKY_USERNAME and OPENSKY_PASSWORD:
            self._token_manager = None
            self._use_oauth2    = False
            print("[OpenSky] Using basic auth (username/password)")
        else:
            self._token_manager = None
            self._use_oauth2    = False
            print("[OpenSky] ⚠  No credentials — using anonymous access (rate-limited)")

    def _get_headers(self) -> dict:
        """Build auth headers for the request."""
        if self._use_oauth2:
            token = self._token_manager.get_token()
            if token:
                return {"Authorization": f"Bearer {token}"}
            print("[OpenSky] ⚠  Could not get OAuth2 token — trying without auth")
            return {}
        return {}

    def _get_auth(self):
        """Return basic auth tuple or None."""
        if not self._use_oauth2 and OPENSKY_USERNAME and OPENSKY_PASSWORD:
            return (OPENSKY_USERNAME, OPENSKY_PASSWORD)
        return None

    def fetch(self) -> list[dict]:
        """
        Call the OpenSky API and return a list of normalized aircraft dicts.
        Returns an empty list on error so the caller can handle gracefully.
        """
        try:
            print("[OpenSky] Fetching live aircraft data…")
            resp = requests.get(
                OPENSKY_URL,
                headers=self._get_headers(),
                auth=self._get_auth(),
                timeout=REQUEST_TIMEOUT,
            )

            if resp.status_code == 429:
                print("[OpenSky] ⚠  Rate-limited (HTTP 429). Will retry next cycle.")
                return []

            if resp.status_code == 401:
                print("[OpenSky] ❌ Authentication failed — check credentials in .env")
                if self._use_oauth2:
                    # Force token refresh next cycle
                    self._token_manager._access_token = None
                return []

            if not resp.ok:
                print(f"[OpenSky] ❌ HTTP {resp.status_code}: {resp.text[:200]}")
                return []

            data   = resp.json()
            states = data.get("states") or []
            print(f"[OpenSky] ✅ Received {len(states)} aircraft states.")

            aircraft = []
            for state in states:
                callsign_raw = state[1]
                if not callsign_raw or not callsign_raw.strip():
                    continue

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
        from core.database import DatabaseManager
        from models.models import FlightModel

        self._db     = DatabaseManager()
        self._Flight = FlightModel

        self._has_telemetry = all(
            hasattr(self._Flight, col) for col in TELEMETRY_FIELDS
        )
        if self._has_telemetry:
            print("[Updater] Telemetry columns detected — lat/lon/alt/vel will be updated.")
        else:
            print("[Updater] No telemetry columns on FlightModel — only status will be updated.")

    @staticmethod
    def _resolve_status(on_ground: bool | None) -> str:
        if on_ground is True:
            return "Arrived"
        return "In Air"

    def update(self, aircraft: list[dict]) -> int:
        if not aircraft:
            return 0

        lookup: dict[str, dict] = {}
        for a in aircraft:
            fn = a["flight_number"].upper()
            lookup[fn] = a

        updated_count = 0

        with self._db.session_scope() as session:
            for fn, ac in lookup.items():
                try:
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

        return updated_count


# ── Main Loop ─────────────────────────────────────────────────────────────────

class OpenSkyStatusUpdaterService:

    def __init__(self):
        self._fetcher = OpenSkyFetcher()
        self._updater = FlightStatusUpdater()

    def run_once(self) -> dict:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n[Service] ── Cycle start: {ts} ──────────────────────────────")

        aircraft = self._fetcher.fetch()
        if not aircraft:
            print("[Service] No usable aircraft data — skipping DB update.")
            return {"timestamp": ts, "fetched": 0, "updated": 0}

        updated = self._updater.update(aircraft)
        print(f"[Service] ✅ Updated {updated} flight row(s) from {len(aircraft)} aircraft callsigns.")
        return {"timestamp": ts, "fetched": len(aircraft), "updated": updated}

    def run(self):
        print("=" * 62)
        print("  Beumer Group FMS — OpenSky Real-Time Status Updater")
        print(f"  Poll interval : {POLL_INTERVAL}s")
        auth_mode = "OAuth2" if (OPENSKY_CLIENT_ID and OPENSKY_CLIENT_SECRET) else "Basic Auth"
        print(f"  Auth mode     : {auth_mode}")
        print(f"  Client ID     : {OPENSKY_CLIENT_ID or OPENSKY_USERNAME or '(anonymous)'}")
        print("=" * 62)

        while True:
            try:
                self.run_once()
            except KeyboardInterrupt:
                print("\n[Service] Interrupted by user. Shutting down.")
                break
            except Exception as e:
                print(f"[Service] ❌ Unhandled error in cycle: {e}")

            print(f"[Service] Sleeping {POLL_INTERVAL}s until next cycle…\n")
            time.sleep(POLL_INTERVAL)


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    service = OpenSkyStatusUpdaterService()
    service.run()