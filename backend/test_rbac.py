"""
Quick RBAC integration test — run from backend directory.
Tests all role-based access scenarios.
"""
import requests

BASE = "http://localhost:8000"

def h(token): return {"Authorization": f"Bearer {token}"}

def sep(title): print(f"\n{'='*55}\n  {title}\n{'='*55}")

# ── 1. Admin login ────────────────────────────────────────
sep("1. ADMIN LOGIN")
r = requests.post(f"{BASE}/auth/login", json={"username": "admin", "password": "admin123"})
print(f"  Status: {r.status_code}")
d = r.json()
print(f"  role={d.get('role')}  airport_id={d.get('airport_id')}")
ADMIN = d["access_token"]

# ── 2. Fetch airports ─────────────────────────────────────
sep("2. GET AIRPORTS")
airports = requests.get(f"{BASE}/airports", headers=h(ADMIN)).json()
print(f"  Found {len(airports)} airports")
for a in airports:
    print(f"    id={a['id']}  code={a['code']}  name={a['name']}")
NMIA = next(a for a in airports if a["code"] == "NMIA")
DEL  = next(a for a in airports if a["code"] == "DEL")

# ── 3. Register staff for NMIA ────────────────────────────
sep("3. REGISTER NMIA STAFF")
r = requests.post(f"{BASE}/auth/register", headers=h(ADMIN), json={
    "username": "nmia_staff", "password": "staff123",
    "email": "staff@nmia.com", "full_name": "NMIA Staff",
    "role": "staff", "airport_id": NMIA["id"]
})
print(f"  Status: {r.status_code}  (409=already exists is OK)")
resp = r.json()
if r.status_code == 201:
    u = resp["user"]
    print(f"  user={u['username']}  role={u['role']}  airport_id={u['airport_id']}")

# ── 4. Register viewer for DEL ────────────────────────────
sep("4. REGISTER DEL VIEWER")
r = requests.post(f"{BASE}/auth/register", headers=h(ADMIN), json={
    "username": "del_viewer", "password": "viewer123",
    "email": "viewer@del.com", "full_name": "DEL Viewer",
    "role": "viewer", "airport_id": DEL["id"]
})
print(f"  Status: {r.status_code}  (409=already exists is OK)")
if r.status_code == 201:
    u = r.json()["user"]
    print(f"  user={u['username']}  role={u['role']}  airport_id={u['airport_id']}")

# ── 5. Staff without airport_id must be rejected ──────────
sep("5. REGISTER STAFF WITHOUT AIRPORT (expect 400)")
r = requests.post(f"{BASE}/auth/register", headers=h(ADMIN), json={
    "username": "bad_staff", "password": "bad123",
    "email": "bad@x.com", "full_name": "Bad Staff", "role": "staff"
})
print(f"  Status: {r.status_code}  Expected: 400")
print(f"  Detail: {r.json().get('detail')}")

# ── 6. Staff login ────────────────────────────────────────
sep("6. NMIA STAFF LOGIN")
r = requests.post(f"{BASE}/auth/login", json={"username": "nmia_staff", "password": "staff123"})
print(f"  Status: {r.status_code}")
d = r.json()
print(f"  role={d.get('role')}  airport_id={d.get('airport_id')}  expected_airport={NMIA['id']}")
STAFF = d["access_token"]

# ── 7. Staff creates flight (airport auto-assigned from profile) ───
sep("7. STAFF CREATES FLIGHT — airport auto-assigned")
r = requests.post(f"{BASE}/flights", headers=h(STAFF), json={
    "flight_number": "TEST-001", "airline_code": "6E",
    "airport_id": DEL["id"],           # Staff sends wrong airport — must be overridden
    "origin": "Delhi (DEL)",
    "destination": "Navi Mumbai (NMIA)",
    "departure_time": "10:00", "arrival_time": "12:00",
    "gate_number": "G5", "terminal_number": "T1",
    "status": "Scheduled", "flight_type": "arrival",
})
print(f"  Status: {r.status_code}  Expected: 201")
if r.status_code == 201:
    fl = r.json()
    ok = fl["airport_id"] == NMIA["id"]
    print(f"  Flight airport_id={fl['airport_id']}  NMIA_id={NMIA['id']}  CORRECT={ok}")
    FLIGHT_ID = fl["id"]
else:
    print(f"  Error: {r.json()}")
    FLIGHT_ID = None

# ── 8. Staff tries PUT — must fail 403 ───────────────────
if FLIGHT_ID:
    sep("8. STAFF UPDATE (expect 403)")
    r = requests.put(f"{BASE}/flights/{FLIGHT_ID}", headers=h(STAFF), json={"status": "Boarding"})
    print(f"  Status: {r.status_code}  Expected: 403")
    print(f"  Detail: {r.json().get('detail')}")

# ── 9. Staff tries DELETE — must fail 403 ────────────────
if FLIGHT_ID:
    sep("9. STAFF DELETE (expect 403)")
    r = requests.delete(f"{BASE}/flights/{FLIGHT_ID}", headers=h(STAFF))
    print(f"  Status: {r.status_code}  Expected: 403")
    print(f"  Detail: {r.json().get('detail')}")

# ── 10. Admin updates — must succeed ─────────────────────
if FLIGHT_ID:
    sep("10. ADMIN UPDATE (expect 200)")
    r = requests.put(f"{BASE}/flights/{FLIGHT_ID}", headers=h(ADMIN), json={"status": "Boarding"})
    print(f"  Status: {r.status_code}  Expected: 200")
    if r.status_code == 200:
        print(f"  New status: {r.json()['status']}")

# ── 11. Viewer login + GET /flights scoped to DEL ─────────
sep("11. DEL VIEWER — GET /flights (scoped to DEL only)")
r = requests.post(f"{BASE}/auth/login", json={"username": "del_viewer", "password": "viewer123"})
VIEWER = r.json()["access_token"]
r = requests.get(f"{BASE}/flights", headers=h(VIEWER))
flights = r.json()
ids_seen = set(f["airport_id"] for f in flights)
ok = ids_seen == set() or ids_seen == {DEL["id"]}
print(f"  Status: {r.status_code}  Airport IDs in response: {ids_seen}")
print(f"  Scoping correct: {ok}  (expected only id={DEL['id']} or empty)")

# ── 12. Viewer tries POST — must fail 403 ────────────────
sep("12. VIEWER CREATES FLIGHT (expect 403)")
r = requests.post(f"{BASE}/flights", headers=h(VIEWER), json={
    "flight_number": "VW-001", "airline_code": "6E",
    "origin": "X", "destination": "Y",
    "departure_time": "08:00", "arrival_time": "10:00",
    "gate_number": "G1", "terminal_number": "T1",
    "status": "Scheduled", "flight_type": "arrival",
})
print(f"  Status: {r.status_code}  Expected: 403")
print(f"  Detail: {r.json().get('detail')}")

# ── 13. Admin deletes test flight ─────────────────────────
if FLIGHT_ID:
    sep("13. ADMIN DELETES TEST FLIGHT")
    r = requests.delete(f"{BASE}/flights/{FLIGHT_ID}", headers=h(ADMIN))
    print(f"  Status: {r.status_code}  Expected: 200")

# ── 14. /me returns airport_id ────────────────────────────
sep("14. /me RETURNS airport_id")
r = requests.get(f"{BASE}/auth/me", headers=h(STAFF))
me = r.json()
print(f"  role={me.get('role')}  airport_id={me.get('airport_id')}  full_name={me.get('full_name')}")

# ── 15. GET /users admin only ─────────────────────────────
sep("15. GET /users (admin-only)")
r = requests.get(f"{BASE}/users", headers=h(ADMIN))
print(f"  Admin access: {r.status_code}  Expected: 200  Count: {len(r.json())}")
r2 = requests.get(f"{BASE}/users", headers=h(STAFF))
print(f"  Staff access: {r2.status_code}  Expected: 403")

print("\n" + "═"*55)
print("  ALL RBAC TESTS COMPLETE")
print("═"*55)
