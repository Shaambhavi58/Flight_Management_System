import json
from collections import Counter

def load_json(file_name):
    with open(file_name, "r", encoding="utf-8") as f:
        return json.load(f)

arrivals = load_json("hyd_arrivals_clean.json")
departures = load_json("hyd_departures_clean.json")

def count_missing(data, field):
    return sum(1 for item in data if not item.get(field))

print("\n========== HYD DATA AUDIT ==========")

print("\n--- BASIC COUNT ---")
print("Arrivals:", len(arrivals))
print("Departures:", len(departures))
print("Total:", len(arrivals) + len(departures))

print("\n--- MISSING DATA ---")
print("Missing Arrival Carousel/Belt:", count_missing(arrivals, "carousel_number"))
print("Missing Departure Gate:", count_missing(departures, "gate_number"))
print("Missing Departure Terminal:", count_missing(departures, "terminal_number"))

print("\n--- STATUS DISTRIBUTION ---")
all_flights = arrivals + departures
print(Counter(f["status"] for f in all_flights))

print("\n--- TOP 10 AIRLINES ---")
print(Counter(f["airline"] for f in all_flights).most_common(10))

print("\n--- TOP 10 ARRIVAL ORIGINS ---")
print(Counter(f["origin_iata"] for f in arrivals).most_common(10))

print("\n--- TOP 10 DEPARTURE DESTINATIONS ---")
print(Counter(f["destination_iata"] for f in departures).most_common(10))

print("\n--- INTERNATIONAL ROUTES SAMPLE ---")
international_codes = {"DXB", "DOH", "SIN", "AUH", "BAH", "FRA", "JED", "MCT", "CMB"}

intl_arrivals = [f for f in arrivals if f.get("origin_iata") in international_codes]
intl_departures = [f for f in departures if f.get("destination_iata") in international_codes]

print("International Arrivals:", len(intl_arrivals))
print("International Departures:", len(intl_departures))

print("\nAudit completed.")