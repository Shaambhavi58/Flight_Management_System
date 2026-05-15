import sqlite3
import os

db_path = 'flight_management.db'
if not os.path.exists(db_path):
    print(f"Error: {db_path} not found.")
    sys.exit(1)

print(f"Checking {db_path}, size: {os.path.getsize(db_path)} bytes")

conn = sqlite3.connect(db_path)
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()
print(f"Tables: {tables}")

if ('flights',) in tables:
    cursor.execute("SELECT flight_number, status, delay_minutes, delay_reason FROM flights WHERE status = 'Delayed' LIMIT 5")
    rows = cursor.fetchall()
    print("\nDelayed Flights Sample:")
    for r in rows:
        print(r)

    cursor.execute("SELECT count(*) FROM flights WHERE status = 'Delayed' AND delay_minutes > 0")
    count = cursor.fetchone()[0]
    print(f"\nDelayed flights with minutes > 0: {count}")

conn.close()
