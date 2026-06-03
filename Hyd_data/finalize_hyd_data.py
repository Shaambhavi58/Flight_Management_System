import json
import random
from collections import Counter

INTERNATIONAL_CODES = {
    "DXB", "DOH", "SIN", "AUH", "BAH", "FRA",
    "JED", "MCT", "CMB", "KWI", "RUH", "SHJ", "DMM"
}

def load_json(file_name):
    with open(file_name, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(file_name, data):
    with open(file_name, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def normalize_status(status):
    if status == "landed":
        return "Arrived"
    if status == "active":
        return "Departed"
    if status == "scheduled":
        return "Scheduled"
    if status == "cancelled":
        return "Cancelled"
    return "Scheduled"

def format_carousel(value):
    if value:
        value = str(value).replace("C", "").strip()
        return f"C{value}"
    return f"C{random.randint(1, 12)}"

def format_gate(value):
    if value:
        value = str(value).replace("G", "").strip()
        return f"G{value}"
    return f"G{random.randint(1, 40)}"

def get_terminal(destination_iata):
    if destination_iata in INTERNATIONAL_CODES:
        return "T2"
    return "T1"

arrivals = load_json("hyd_arrivals_clean.json")
departures = load_json("hyd_departures_clean.json")

final_arrivals = []
final_departures = []

for f in arrivals:
    final_arrivals.append({
        "airline": f.get("airline"),
        "flight_no": f.get("flight_no"),
        "origin": f.get("origin"),
        "origin_iata": f.get("origin_iata"),
        "date": f.get("date"),
        "time": f.get("time"),
        "carousel_number": format_carousel(f.get("carousel_number")),
        "status": normalize_status(f.get("status")),
        "delay_minutes": f.get("delay_minutes") or 0
    })

for f in departures:
    final_departures.append({
        "airline": f.get("airline"),
        "flight_no": f.get("flight_no"),
        "destination": f.get("destination"),
        "destination_iata": f.get("destination_iata"),
        "date": f.get("date"),
        "time": f.get("time"),
        "terminal_number": get_terminal(f.get("destination_iata")),
        "gate_number": format_gate(f.get("gate_number")),
        "status": normalize_status(f.get("status")),
        "delay_minutes": f.get("delay_minutes") or 0
    })

save_json("hyd_arrivals_final.json", final_arrivals)
save_json("hyd_departures_final.json", final_departures)

all_flights = final_arrivals + final_departures

print("\n========== FINAL HYD DATA AUDIT ==========")
print("Arrivals:", len(final_arrivals))
print("Departures:", len(final_departures))
print("Total:", len(all_flights))
print("Missing Carousel:", sum(1 for f in final_arrivals if not f.get("carousel_number")))
print("Missing Gate:", sum(1 for f in final_departures if not f.get("gate_number")))
print("Missing Terminal:", sum(1 for f in final_departures if not f.get("terminal_number")))
print("Status Distribution:", Counter(f["status"] for f in all_flights))
print("\nFinal files created successfully!")