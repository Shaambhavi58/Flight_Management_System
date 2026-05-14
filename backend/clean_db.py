from sqlalchemy import text
from core.database import DatabaseManager

db = DatabaseManager()

# 1. First delete logs for flights that are about to be deleted
log_query = text("""
DELETE FROM carousel_change_log
WHERE flight_id NOT IN (
    SELECT min_id FROM (
        SELECT MIN(id) as min_id
        FROM flights
        GROUP BY flight_number, departure_time, origin
    ) as temp
);
""")

# 2. Then delete the duplicate flights
flight_query = text("""
DELETE FROM flights
WHERE id NOT IN (
    SELECT min_id FROM (
        SELECT MIN(id) as min_id
        FROM flights
        GROUP BY flight_number, departure_time, origin
    ) as temp
);
""")

with db.session_scope() as session:
    session.execute(log_query)
    session.execute(flight_query)
    session.commit()
    print("Old duplicate data and their logs cleaned successfully.")
