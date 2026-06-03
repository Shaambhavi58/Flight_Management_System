import json
import random
from collections import Counter, defaultdict

INPUT_FILE = "hyd_all_flights_merged.json"

PREFERRED_PREFIXES = ("6E", "AI", "IX", "QP", "EK")
INTERNATIONAL_CODES = {"DXB", "DOH", "SIN", "AUH", "BAH", "FRA", "JED", "MCT", "CMB", "KWI", "RUH", "SHJ", "DMM"}


def load_json(file_name):
    with open(file_name, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(file_name, data):
    with open(file_name, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def get_flight_no(f):
    return f.get("flight", {}).get("iata") or ""


def get_airline(f):
    return f.get("airline", {}).get("name") or "Unknown Airline"


def get_route_key(f):
    dep = f.get("departure", {})
    arr = f.get("arrival", {})

    return (
        dep.get("iata"),
        arr.get("iata"),
        dep.get("scheduled"),
        arr.get("scheduled"),
        f.get("flight_date")
    )


def choose_best_flight(group):
    for prefix in PREFERRED_PREFIXES:
        for f in group:
            if get_flight_no(f).upper().startswith(prefix):
                return f

    return group[0]


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


def format_time(dt):
    if not dt:
        return "00:00"
    return dt[11:16]


def format_date(dt):
    if not dt:
        return None
    return dt[:10]


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


def get_terminal(iata):
    return "T2" if iata in INTERNATIONAL_CODES else "T1"


def get_makeup_area():
    return f"M{random.randint(1, 20)}"


raw = load_json(INPUT_FILE)
flights = raw.get("data", [])

print("\nBefore cleanup:", len(flights))
print("Top airlines before:", Counter(get_airline(f) for f in flights).most_common(10))

groups = defaultdict(list)

for flight in flights:
    key = get_route_key(flight)
    groups[key].append(flight)

deduplicated = []
removed = []

for key, group in groups.items():
    if len(group) == 1:
        deduplicated.append(group[0])
    else:
        keep = choose_best_flight(group)
        deduplicated.append(keep)

        for f in group:
            if f is not keep:
                removed.append({
                    "kept": get_flight_no(keep),
                    "removed": get_flight_no(f),
                    "route": f"{key[0]} -> {key[1]}",
                    "reason": "codeshare duplicate"
                })

print("Duplicate groups found:", sum(1 for g in groups.values() if len(g) > 1))
print("Codeshare removed:", len(removed))
print("After cleanup:", len(deduplicated))
print("Top airlines after:", Counter(get_airline(f) for f in deduplicated).most_common(10))

save_json("hyd_all_flights_deduplicated.json", {
    "total_flights": len(deduplicated),
    "data": deduplicated
})

save_json("codeshare_cleanup_report.json", {
    "original_count": len(flights),
    "final_count": len(deduplicated),
    "removed_count": len(removed),
    "removed_flights": removed
})

arrivals = []
departures = []

for f in deduplicated:
    dep = f.get("departure", {})
    arr = f.get("arrival", {})
    airline = get_airline(f)
    flight_no = get_flight_no(f)
    status = normalize_status(f.get("flight_status"))

    if arr.get("iata") == "HYD":
        arrivals.append({
            "airline": airline,
            "flight_no": flight_no,
            "origin": dep.get("airport"),
            "origin_iata": dep.get("iata"),
            "date": format_date(arr.get("scheduled")),
            "time": format_time(arr.get("scheduled")),
            "carousel_number": format_carousel(arr.get("baggage")),
            "status": status,
            "delay_minutes": arr.get("delay") or 0
        })

    elif dep.get("iata") == "HYD":
        departures.append({
            "airline": airline,
            "flight_no": flight_no,
            "destination": arr.get("airport"),
            "destination_iata": arr.get("iata"),
            "date": format_date(dep.get("scheduled")),
            "time": format_time(dep.get("scheduled")),
            "terminal_number": get_terminal(arr.get("iata")),
            "gate_number": format_gate(dep.get("gate")),
            "makeup_area": get_makeup_area(),
            "status": status,
            "delay_minutes": dep.get("delay") or arr.get("delay") or 0
        })

save_json("hyd_arrivals_final.json", arrivals)
save_json("hyd_departures_final.json", departures)

print("\nFinal files regenerated:")
print("Arrivals:", len(arrivals))
print("Departures:", len(departures))
print("Total:", len(arrivals) + len(departures))
print("Missing carousel:", sum(1 for x in arrivals if not x.get("carousel_number")))
print("Missing gate:", sum(1 for x in departures if not x.get("gate_number")))
print("Missing makeup area:", sum(1 for x in departures if not x.get("makeup_area")))