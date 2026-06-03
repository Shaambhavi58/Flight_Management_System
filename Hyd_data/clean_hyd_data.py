import json
from datetime import datetime

def format_date_time(dt):
    if not dt:
        return None, None
    parsed = datetime.fromisoformat(dt.replace("Z", "+00:00"))
    return parsed.date().isoformat(), parsed.strftime("%H:%M")

def clean_flight(flight):
    flight_type = flight.get("flight_type")

    airline = flight.get("airline", {}).get("name")
    flight_no = flight.get("flight", {}).get("iata")
    status = flight.get("flight_status", "scheduled")

    departure = flight.get("departure", {})
    arrival = flight.get("arrival", {})

    if flight_type == "arrival":
        date, time = format_date_time(arrival.get("scheduled"))

        return {
            "airline": airline,
            "flight_no": flight_no,
            "origin": departure.get("airport"),
            "origin_iata": departure.get("iata"),
            "date": date,
            "time": time,
            "carousel_number": arrival.get("baggage"),
            "status": status,
            "delay_minutes": arrival.get("delay")
        }

    if flight_type == "departure":
        date, time = format_date_time(departure.get("scheduled"))

        return {
            "airline": airline,
            "flight_no": flight_no,
            "destination": arrival.get("airport"),
            "destination_iata": arrival.get("iata"),
            "date": date,
            "time": time,
            "terminal_number": departure.get("terminal"),
            "gate_number": departure.get("gate"),
            "status": status,
            "delay_minutes": departure.get("delay") or arrival.get("delay")
        }

    return None


with open("hyd_all_flights_merged.json", "r", encoding="utf-8") as f:
    merged = json.load(f)

arrivals = []
departures = []

for flight in merged.get("data", []):
    cleaned = clean_flight(flight)

    if not cleaned:
        continue

    if flight.get("flight_type") == "arrival":
        arrivals.append(cleaned)
    elif flight.get("flight_type") == "departure":
        departures.append(cleaned)

with open("hyd_arrivals_clean.json", "w", encoding="utf-8") as f:
    json.dump(arrivals, f, indent=4)

with open("hyd_departures_clean.json", "w", encoding="utf-8") as f:
    json.dump(departures, f, indent=4)

print("Clean files created successfully!")
print("Arrivals:", len(arrivals))
print("Departures:", len(departures))