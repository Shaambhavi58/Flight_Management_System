from sqlalchemy import text
from core.database import DatabaseManager

db = DatabaseManager()

query = text("""
SELECT flight_number, departure_time, origin, COUNT(*) as c
FROM flights
GROUP BY flight_number, departure_time, origin
HAVING c > 1;
""")

with db.session_scope() as session:
    result = session.execute(query).fetchall()
    if not result:
        print("No duplicates found based on flight_number, departure_time, and origin.")
    else:
        for r in result:
            print(f"Duplicate: {r}")
