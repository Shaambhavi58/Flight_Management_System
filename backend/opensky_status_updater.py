"""
opensky_status_updater.py — Real-Time Flight Status Updater
============================================================
Polls the OpenSky Network API every 300 seconds to fetch live
aircraft transponder data and updates matching flight statuses
in the MySQL database.

NEW: When a flight transitions to "Arrived", carousel_number is
auto-assigned via assign_carousel() from service.py, and a
CAROUSEL_ASSIGNED event is published to RabbitMQ (BHS feed).
"""

import os
import sys
import time
import requests
from datetime import datetime
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
load_dotenv()

OPENSKY_URL       = "https://opensky-network.org/api/states/all"
OPENSKY_TOKEN_URL = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"

OPENSKY_CLIENT_ID     = os.getenv("OPENSKY_CLIENT_ID", "")
OPENSKY_CLIENT_SECRET = os.getenv("OPENSKY_CLIENT_SECRET", "")
OPENSKY_USERNAME = os.getenv("OPENSKY_USERNAME", "")
OPENSKY_PASSWORD = os.getenv("OPENSKY_PASSWORD", "")

POLL_INTERVAL   = 300
REQUEST_TIMEOUT = 30

CALLSIGN_PREFIX_MAP = {
    "AIC": "AI",
    "IGO": "6E",
    "AXB": "IX",
}

TELEMETRY_FIELDS = ("latitude", "longitude", "altitude", "velocity")


def normalize_callsign(raw: str) -> str | None:
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


class OAuth2TokenManager:
    def __init__(self, client_id: str, client_secret: str):
        self._client_id     = client_id
        self._client_secret = client_secret
        self._access_token  = None
        self._token_expiry  = 0

    def get_token(self) -> str | None:
        if self._access_token and time.time() < self._token_expiry - 30:
            return self._access_token
        return self._fetch_token()

    def _fetch_token(self) -> str | None:
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
                print(f"[OAuth2] ❌ Token fetch failed — HTTP {resp.status_code}")
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


class OpenSkyFetcher:
    def __init__(self):
        if OPENSKY_CLIENT_ID and OPENSKY_CLIENT_SECRET:
            self._token_manager = OAuth2TokenManager(OPENSKY_CLIENT_ID, OPENSKY_CLIENT_SECRET)
            self._use_oauth2 = True
        elif OPENSKY_USERNAME and OPENSKY_PASSWORD:
            self._token_manager = None
            self._use_oauth2    = False
        else:
            self._token_manager = None
            self._use_oauth2    = False

    def _get_headers(self) -> dict:
        if self._use_oauth2:
            token = self._token_manager.get_token()
            if token:
                return {"Authorization": f"Bearer {token}"}
        return {}

    def _get_auth(self):
        if not self._use_oauth2 and OPENSKY_USERNAME and OPENSKY_PASSWORD:
            return (OPENSKY_USERNAME, OPENSKY_PASSWORD)
        return None

    def fetch(self) -> list[dict]:
        try:
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
                print("[OpenSky] ❌ Authentication failed")
                if self._use_oauth2:
                    self._token_manager._access_token = None
                return []
            if not resp.ok:
                print(f"[OpenSky] ❌ HTTP {resp.status_code}")
                return []

            data   = resp.json()
            states = data.get("states") or []
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
        except Exception as e:
            print(f"[OpenSky] ❌ Fetch error: {e}")
            return []


class FlightStatusUpdater:
    """
    Updates flight statuses from OpenSky data.
    NEW: When a flight transitions to Arrived, auto-assigns a carousel
    and publishes CAROUSEL_ASSIGNED to RabbitMQ (BHS notification).
    """

    def __init__(self):
        from core.database import DatabaseManager
        from models.models import FlightModel
        from services.service import assign_carousel, publish_bhs_event
        from services.repository import CarouselRepository

        self._db              = DatabaseManager()
        self._Flight          = FlightModel
        self._assign_carousel = assign_carousel
        self._publish_bhs     = publish_bhs_event
        self._carousel_repo   = CarouselRepository()

        self._has_telemetry = all(
            hasattr(self._Flight, col) for col in TELEMETRY_FIELDS
        )

    @staticmethod
    def _resolve_status(on_ground: bool | None) -> str:
        if on_ground is True:
            return "Arrived"
        return "Departed" if on_ground is False else "Scheduled"

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
                        old_status = flight.status
                        flight.status = new_status

                        # ── Auto-assign carousel when flight transitions to Arrived ──
                        # This is the BHS integration trigger point.
                        # Only assign if not already assigned (avoid overwriting manual changes).
                        if new_status == "Arrived" and old_status != "Arrived" and not flight.carousel_number:
                            carousel = self._assign_carousel(flight.flight_number, flight.terminal_number)
                            flight.carousel_number = carousel

                            # Write to carousel_change_log
                            self._carousel_repo.log_change(
                                session,
                                flight_id=flight.id,
                                flight_number=flight.flight_number,
                                old_carousel=None,
                                new_carousel=carousel,
                                changed_by="opensky-updater",
                                reason="Auto-assigned when OpenSky confirmed on_ground=True",
                                event_type="CAROUSEL_ASSIGNED",
                            )

                            # Publish to BHS queue
                            self._publish_bhs("CAROUSEL_ASSIGNED", {
                                "flight_number": flight.flight_number,
                                "terminal":      flight.terminal_number,
                                "new_carousel":  carousel,
                                "old_carousel":  None,
                                "airport_id":    flight.airport_id,
                                "changed_by":    "opensky-updater",
                            })

                            print(f"[Updater] ✈ {fn} Arrived → Carousel {carousel} assigned")

                        if self._has_telemetry:
                            if ac["latitude"]  is not None: flight.latitude  = ac["latitude"]
                            if ac["longitude"] is not None: flight.longitude = ac["longitude"]
                            if ac["altitude"]  is not None: flight.altitude  = ac["altitude"]
                            if ac["velocity"]  is not None: flight.velocity  = ac["velocity"]

                        updated_count += 1

                except Exception as e:
                    print(f"[Updater] ⚠  Error updating flight {fn}: {e}")

        return updated_count


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


if __name__ == "__main__":
    service = OpenSkyStatusUpdaterService()
    service.run()