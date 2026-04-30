from core.database import DatabaseManager
from sqlalchemy import text

db = DatabaseManager()
with db.session_scope() as session:
    session.execute(text("DELETE FROM flights"))
    session.commit()
    print("Deleted all flights.")
