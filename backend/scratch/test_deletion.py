import sys
import os
sys.path.append(os.getcwd())

from core.database import DatabaseManager
from models.models import FlightModel, CarouselChangeLog

db = DatabaseManager()
with db.session_scope() as session:
    try:
        print("Starting deletion...")
        # 1. Delete logs
        logs_deleted = session.query(CarouselChangeLog).delete(synchronize_session=False)
        print(f"Logs deleted: {logs_deleted}")
        
        # 2. Delete flights
        flights_deleted = session.query(FlightModel).delete(synchronize_session=False)
        print(f"Flights deleted: {flights_deleted}")
        
        session.flush()
        print("Deletion successful (will be committed by session_scope)")
    except Exception as e:
        print(f"Deletion failed: {e}")
        raise
