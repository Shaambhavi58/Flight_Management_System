import json
import glob
import os

def load_flights(folder_name, flight_type):
    flights = []
    seen = set()
    duplicates = 0

    files = glob.glob(os.path.join(folder_name, "*.json"))

    for file in files:
        print(f"Reading {file}")

        with open(file, "r", encoding="utf-8") as f:
            raw = json.load(f)

        data = raw.get("data", [])
        print(f"Loaded {len(data)} flights")

        for flight in data:
            flight["flight_type"] = flight_type

            flight_iata = flight.get("flight", {}).get("iata")
            scheduled = flight.get("departure", {}).get("scheduled")
            unique_key = f"{flight_iata}_{scheduled}_{flight_type}"

            if unique_key in seen:
                duplicates += 1
                continue

            seen.add(unique_key)
            flights.append(flight)

    return flights, duplicates


arrivals, arrival_duplicates = load_flights("Arrival", "arrival")
departures, departure_duplicates = load_flights("Departure", "departure")

all_flights = arrivals + departures

output = {
    "summary": {
        "arrival_flights": len(arrivals),
        "departure_flights": len(departures),
        "total_flights": len(all_flights),
        "duplicates_removed": arrival_duplicates + departure_duplicates
    },
    "data": all_flights
}

with open("hyd_all_flights_merged.json", "w", encoding="utf-8") as f:
    json.dump(output, f, indent=4)

print("\nMerged successfully!")
print(output["summary"])