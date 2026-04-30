from sqlalchemy import text
from core.database import DatabaseManager

db = DatabaseManager()

query = text("""
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
    session.execute(query)
    session.commit()
    print("Old duplicate data cleaned successfully.")
