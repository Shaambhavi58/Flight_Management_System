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
from models.models import AirlineModel, AirportModel, UserModel
from services.auth_service import AuthService
from utils.status_updater import status_update_loop

from controllers.auth_controller import router as auth_router
from controllers.airport_controller import router as airport_router
from controllers.flight_controller import router as flight_router


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


# ── Lifespan ─────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    db = DatabaseManager()
    db.create_tables()          # Creates tables only if they don't exist (no data loss)
    seed_airlines(db)
    seed_airports(db)
    seed_admin(db)

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
# ── CLEAR ALL FLIGHTS (USED BY RABBITMQ PUBLISHER) ───────────────

@app.delete("/flights/clear-all", tags=["Flights"])
def clear_all_flights(admin: dict = Depends(require_admin)):
    """
    Clears all flights from database.
    Used by flight_publisher before generating new schedule.
    """
    count = flight_service.clear_all_flights()
    print(f"[API] Cleared {count} flights before new publish.")
    return {"message": f"Cleared {count} flights"}