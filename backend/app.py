"""
app.py — FastAPI Application for Beumer Group Flight Management System.

Serves the REST API, the static GUI, seeds data, and starts the RabbitMQ consumer.
Single Page Application — all pages served from one index.html.
"""

import os
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer
from fastapi.openapi.utils import get_openapi
from services.service import FlightService

flight_service = FlightService()
from core.database import DatabaseManager
from models.models import AirlineModel, AirportModel, UserModel, FlightStatusHistory, GateModel, GateAssignmentModel
from services.auth_service import AuthService
from utils.status_updater import status_update_loop

from controllers.auth_controller import router as auth_router
from controllers.airport_controller import router as airport_router
from controllers.flight_controller import router as flight_router
from controllers.analytics_controller import router as analytics_router


# ── Seed Data ────────────────────────────────────────────────────

AIRLINES_SEED = [
    {"name": "IndiGo",    "code": "6E"},
    {"name": "Akasa Air", "code": "QP"},
    {"name": "Emirates",  "code": "EK"},
    {"name": "Air India", "code": "AI"},
    {"name": "Vistara",   "code": "UK"},
]

AIRPORTS_SEED = [
    {"name": "Indira Gandhi International Airport",             "code": "DEL",  "city": "Delhi"},
    {"name": "Chhatrapati Shivaji Maharaj International Airport","code": "BOM",  "city": "Mumbai"},
    {"name": "Navi Mumbai International Airport",               "code": "NMIA", "city": "Navi Mumbai"},
    {"name": "Kempegowda International Airport",                "code": "BLR",  "city": "Bangalore"},
    {"name": "Rajiv Gandhi International Airport",              "code": "HYD",  "city": "Hyderabad"},
]

def seed_airlines(db: DatabaseManager):
    """Insert airlines if they don't already exist."""
    with db.session_scope() as session:
        for data in AIRLINES_SEED:
            if not session.query(AirlineModel).filter_by(code=data["code"]).first():
                session.add(AirlineModel(**data))
                print(f"[Seed] Added airline: {data['name']} ({data['code']})")

def seed_airports(db: DatabaseManager):
    """Insert airports if they don't already exist."""
    with db.session_scope() as session:
        for data in AIRPORTS_SEED:
            if not session.query(AirportModel).filter_by(code=data["code"]).first():
                session.add(AirportModel(**data))
                print(f"[Seed] Added airport: {data['name']} ({data['code']})")

def seed_admin(db: DatabaseManager):
    """Create the default admin user if not exists (airport_id=NULL for admin)."""
    auth = AuthService()
    with db.session_scope() as session:
        if not session.query(UserModel).filter_by(username="admin").first():
            session.add(UserModel(
                username="admin",
                password_hash=auth.hash_password("admin123"),
                email="admin@beumergroup.com",
                full_name="System Administrator",
                role="admin",
                airport_id=None,  # admin is not scoped to any airport
            ))
            print("[Seed] Added default admin user (admin / admin123)")

def start_rabbitmq_consumer():
    """Start the RabbitMQ consumer in a background thread."""
    try:
        from utils.rabbitmq import MessageConsumer
        consumer = MessageConsumer()
        consumer.start_in_thread()
        print("[App] RabbitMQ consumer started in background thread.")
    except Exception as e:
        print(f"[App] Could not start RabbitMQ consumer: {e}")
        print("[App] The app will still work — flights can be added via the API.")


def verify_carousel_schema(db: DatabaseManager):
    """
    Diagnostic check: Verify carousel_number exists in flights table 
    and carousel_change_log table exists.
    Raises RuntimeError if integration is incomplete.
    """
    from sqlalchemy import inspect
    inspector = inspect(db.engine)
    
    # 1. Check for table existence
    tables = inspector.get_table_names()
    if "carousel_change_log" not in tables:
        print("[CRITICAL] Missing table: carousel_change_log")
        raise RuntimeError("Database migration incomplete: carousel_change_log table is missing.")
        
    # 2. Check for column existence in flights
    columns = [c["name"] for c in inspector.get_columns("flights")]
    if "carousel_number" not in columns:
        print("[CRITICAL] Missing column in 'flights': carousel_number")
        raise RuntimeError("Database migration incomplete: 'carousel_number' column is missing from 'flights' table.")

    print("[App] Carousel/BHS integration verified: Schema is healthy.")
    
def verify_delay_schema(db: DatabaseManager):
    """
    Diagnostic check: Ensure delay tracking columns exist.
    If missing (e.g. after update), adds them via ALTER TABLE.
    """
    from sqlalchemy import inspect, text
    inspector = inspect(db.engine)
    columns = [c["name"] for c in inspector.get_columns("flights")]
    
    with db.engine.connect() as conn:
        if "delay_minutes" not in columns:
            print("[Migration] Adding 'delay_minutes' column to 'flights' table...")
            # For SQLite/MySQL, use ALTER TABLE
            conn.execute(text("ALTER TABLE flights ADD COLUMN delay_minutes INTEGER DEFAULT 0 NOT NULL"))
            conn.commit()
        if "delay_reason" not in columns:
            print("[Migration] Adding 'delay_reason' column to 'flights' table...")
            conn.execute(text("ALTER TABLE flights ADD COLUMN delay_reason VARCHAR(50)"))
            conn.commit()
    print("[App] Delay tracking schema verified: healthy.")

def verify_timestamp_schema(db: DatabaseManager):
    """
    Diagnostic check: Ensure updated_at column exists in flights table.
    If missing, adds it via ALTER TABLE.
    """
    from sqlalchemy import inspect, text
    inspector = inspect(db.engine)
    columns = [c["name"] for c in inspector.get_columns("flights")]
    
    with db.engine.connect() as conn:
        if "updated_at" not in columns:
            print("[Migration] Adding 'updated_at' column to 'flights' table...")
            conn.execute(text("ALTER TABLE flights ADD COLUMN updated_at DATETIME"))
            conn.commit()
    print("[App] Timestamp schema verified: healthy.")


def seed_gates_and_assignments(db: DatabaseManager):
    """
    Scans all existing flights, seeds the gates table for any existing unique gates,
    creates active assignments for them, and inserts extra mock gates for rich selection.
    """
    from models.models import FlightModel, GateModel, GateAssignmentModel
    print("[Seed] Synchronizing and seeding gates & assignments...")
    with db.session_scope() as session:
        # 1. Gather all existing flights
        flights = session.query(FlightModel).all()
        for f in flights:
            if not f.gate_number or not f.terminal_number:
                continue
            # Check/insert gate
            gate = session.query(GateModel).filter_by(
                airport_id=f.airport_id,
                terminal_number=f.terminal_number,
                gate_number=f.gate_number
            ).first()
            if not gate:
                gate = GateModel(
                    airport_id=f.airport_id,
                    terminal_number=f.terminal_number,
                    gate_number=f.gate_number,
                    status="Available"
                )
                session.add(gate)
                session.flush()

            # Check/insert active assignment
            assignment = session.query(GateAssignmentModel).filter_by(
                flight_id=f.id,
                gate_id=gate.id,
                assignment_status="Active"
            ).first()
            if not assignment:
                assignment = GateAssignmentModel(
                    flight_id=f.id,
                    gate_id=gate.id,
                    start_time=f.departure_time,
                    end_time=f.arrival_time,
                    assignment_status="Active"
                )
                session.add(assignment)

        # 2. Add some extra gates to each airport/terminal for options!
        # Airports: 1 to 5, Terminals: T1, T2, T3
        for airport_id in range(1, 6):
            for term in ["T1", "T2", "T3"]:
                # Let's seed 15 gates per terminal (G1 to G15)
                for g_num in range(1, 16):
                    gate_str = f"G{g_num}"
                    # Skip if already exists
                    existing = session.query(GateModel).filter_by(
                        airport_id=airport_id,
                        terminal_number=term,
                        gate_number=gate_str
                    ).first()
                    if not existing:
                        # Make G13 a "Maintenance" gate for realistic constraint demo!
                        status = "Maintenance" if g_num == 13 else "Available"
                        gate = GateModel(
                            airport_id=airport_id,
                            terminal_number=term,
                            gate_number=gate_str,
                            status=status
                        )
                        session.add(gate)

        session.commit()
    print("[Seed] Gates and assignments seeding complete.")



# ── Lifespan ─────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    db = DatabaseManager()
    db.create_tables()          # Creates tables only if they don't exist (no data loss)
    
    # Audit: Ensure carousel integration migrated correctly
    verify_carousel_schema(db)
    verify_delay_schema(db)
    verify_timestamp_schema(db)

    # Verify flight_status_history table exists (auto-created by create_tables above)
    from sqlalchemy import inspect as sa_inspect
    inspector = sa_inspect(db.engine)
    if "flight_status_history" in inspector.get_table_names():
        print("[App] Flight status history table: ✅ present")
    else:
        print("[App] Flight status history table: ⚠  not found — was it imported?")

    
    seed_airlines(db)
    seed_airports(db)
    seed_admin(db)
    seed_gates_and_assignments(db)

    print(f"[App] Database ready — existing flights preserved.")

    # Start background status updater (updates flight statuses every 60s)
    asyncio.create_task(status_update_loop())
    print("[App] Status updater started — flight statuses update every 60 seconds.")

    # Start RabbitMQ consumer
    start_rabbitmq_consumer()

    print("[App] Beumer Group Flight Management System is READY!")
    print("[App] GUI: http://localhost:8000")
    print("[App] API: http://localhost:8000/docs")

    yield

    print("[App] Shutting down...")


# ── FastAPI App ───────────────────────────────────────────────────
app = FastAPI(
    title="Flight Management System",
    description="Internal Flight Operations API",
    version="1.0",
    lifespan=lifespan,
)

security = HTTPBearer()

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title="Flight Management System",
        version="1.0",
        description="Internal Flight API",
        routes=app.routes,
    )

    openapi_schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT"
        }
    }

    for path in openapi_schema["paths"]:
        for method in openapi_schema["paths"][path]:
            openapi_schema["paths"][path][method]["security"] = [{"BearerAuth": []}]

    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Routers
app.include_router(auth_router)
app.include_router(airport_router)
app.include_router(flight_router)
app.include_router(analytics_router)


# ── Users Endpoint (Admin Only) ───────────────────────────────────────────────
from fastapi import Depends
from controllers.auth_controller import require_admin, get_current_user
from services.auth_service import AuthService as _AuthService

_auth_service = _AuthService()

@app.get("/users", tags=["Auth"])
def get_all_users(admin: dict = Depends(require_admin)):
    """List all registered users (admin only)."""
    return _auth_service.get_all_users()


# ══════════════════════════════════════════════════════════════════
#  SERVE SINGLE PAGE APPLICATION (SPA)
#  All pages are in one index.html — JavaScript handles routing
# ══════════════════════════════════════════════════════════════════

# frontend directory is one level up from backend directory
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")

if os.path.isdir(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

    @app.get("/")
    def serve_app():
        """Serve the main SPA."""
        return FileResponse(os.path.join(frontend_dir, "index.html"))

    @app.get("/login")
    def serve_login():
        return FileResponse(os.path.join(frontend_dir, "index.html"))

    @app.get("/airports-page")
    def serve_airports():
        return FileResponse(os.path.join(frontend_dir, "index.html"))

    @app.get("/flights-page")
    def serve_flights():
        return FileResponse(os.path.join(frontend_dir, "index.html"))

    @app.get("/register-page")
    def serve_register():
        return FileResponse(os.path.join(frontend_dir, "index.html"))
# ══════════════════════════════════════════════════════════════════
#  END OF FILE
# ══════════════════════════════════════════════════════════════════