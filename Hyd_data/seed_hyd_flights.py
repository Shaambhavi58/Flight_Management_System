import json
import os
import sys
from sqlalchemy.exc import IntegrityError

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")

sys.path.append(BACKEND_DIR)

from core.database import DatabaseManager
from models.models import FlightModel, AirlineModel


AIRPORT_ID = 5  # HYD - Rajiv Gandhi International Airport


def load_json(file_name):
    with open(file_name, "r", encoding="utf-8") as f:
        return json.load(f)


def clean_time(value):
    if not value:
        return "00:00"
    return str(value)[:5]


def get_or_create_airline(session, airline_name):
    if not airline_name:
        airline_name = "Unknown Airline"

    existing = session.query(AirlineModel).filter(
        AirlineModel.name == airline_name
    ).first()

    if existing:
        return existing.id

    base_code = "".join(word[0] for word in airline_name.split()[:2]).upper()
    if not base_code:
        base_code = "XX"

    code = base_code
    counter = 1

    while session.query(AirlineModel).filter(AirlineModel.code == code).first():
        code = f"{base_code}{counter}"
        counter += 1

    airline = AirlineModel(code=code, name=airline_name)
    session.add(airline)
    session.flush()

    return airline.id


def flight_exists(session, flight_number, flight_type, time_value, origin, destination):
    query = session.query(FlightModel).filter(
        FlightModel.flight_number == flight_number,
        FlightModel.airport_id == AIRPORT_ID,
        FlightModel.flight_type == flight_type,
        FlightModel.origin == origin,
        FlightModel.destination == destination
    )

    if flight_type == "departure":
        query = query.filter(FlightModel.departure_time == time_value)
    else:
        query = query.filter(FlightModel.arrival_time == time_value)

    return query.first()


def safe_add_flight(session, flight):
    try:
        with session.begin_nested():
            session.add(flight)
            session.flush()
        return True
    except IntegrityError:
        return False


def seed_arrivals(session, arrivals):
    inserted = 0
    skipped = 0

    for item in arrivals:
        flight_number = item.get("flight_no")
        arrival_time = clean_time(item.get("time"))

        origin = item.get("origin_iata") or item.get("origin") or "UNK"
        destination = "HYD"

        if not flight_number:
            skipped += 1
            continue

        

        airline_id = get_or_create_airline(session, item.get("airline"))

        flight = FlightModel(
            flight_number=flight_number,
            airline_id=airline_id,
            airport_id=AIRPORT_ID,
            origin=origin,
            destination=destination,
            departure_time="00:00",
            arrival_time=arrival_time,
            gate_number="NA",
            terminal_number="T1",
            status=item.get("status") or "Scheduled",
            flight_type="arrival",
            carousel_number=item.get("carousel_number"),
            makeup_area=None,
            delay_minutes=item.get("delay_minutes") or 0,
            delay_reason=None
        )

        if safe_add_flight(session, flight):
            inserted += 1
        else:
            print(f"Skipped DB duplicate: {flight_number} | {origin} -> {destination}")
            skipped += 1

    return inserted, skipped


def seed_departures(session, departures):
    inserted = 0
    skipped = 0

    for item in departures:
        flight_number = item.get("flight_no")
        departure_time = clean_time(item.get("time"))

        origin = "HYD"
        destination = item.get("destination_iata") or item.get("destination") or "UNK"

        if not flight_number:
            skipped += 1
            continue

      

        airline_id = get_or_create_airline(session, item.get("airline"))

        flight = FlightModel(
            flight_number=flight_number,
            airline_id=airline_id,
            airport_id=AIRPORT_ID,
            origin=origin,
            destination=destination,
            departure_time=departure_time,
            arrival_time="00:00",
            gate_number=item.get("gate_number") or "G1",
            terminal_number=item.get("terminal_number") or "T1",
            status=item.get("status") or "Scheduled",
            flight_type="departure",
            carousel_number=None,
            makeup_area=item.get("makeup_area") or "M1",
            delay_minutes=item.get("delay_minutes") or 0,
            delay_reason=None
        )

        if safe_add_flight(session, flight):
            inserted += 1
        else:
            print(f"Skipped DB duplicate: {flight_number} | {origin} -> {destination}")
            skipped += 1

    return inserted, skipped


def main():
    arrivals = load_json("hyd_arrivals_final.json")
    departures = load_json("hyd_departures_final.json")

    db = DatabaseManager()

    with db.session_scope() as session:
        arr_inserted, arr_skipped = seed_arrivals(session, arrivals)
        dep_inserted, dep_skipped = seed_departures(session, departures)

    print("\n========== HYD SEED COMPLETED ==========")
    print(f"Arrivals   inserted : {arr_inserted}")
    print(f"Arrivals   skipped  : {arr_skipped}")
    print(f"Departures inserted : {dep_inserted}")
    print(f"Departures skipped  : {dep_skipped}")
    print(f"Total inserted      : {arr_inserted + dep_inserted}")
    print(f"Total skipped       : {arr_skipped + dep_skipped}")


if __name__ == "__main__":
    main()