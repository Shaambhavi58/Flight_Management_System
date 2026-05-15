import sqlite3

conn = sqlite3.connect('flight_management.db')
cursor = conn.cursor()

cursor.execute("SELECT flight_number, status, delay_minutes, delay_reason FROM flights WHERE status = 'Delayed' LIMIT 5")
rows = cursor.fetchall()

print("Delayed Flights Sample:")
for r in rows:
    print(r)

cursor.execute("SELECT count(*) FROM flights WHERE status = 'Delayed' AND delay_minutes > 0")
count = cursor.fetchone()[0]
print(f"Delayed flights with minutes > 0: {count}")

conn.close()
