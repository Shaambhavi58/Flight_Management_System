# ✈️ Beumer Group — Flight Management System

![Python](https://img.shields.io/badge/Python-3.11-blue?style=flat-square&logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi)
![RabbitMQ](https://img.shields.io/badge/RabbitMQ-3.x-FF6600?style=flat-square&logo=rabbitmq)
![MySQL](https://img.shields.io/badge/MySQL-8.0-4479A1?style=flat-square&logo=mysql)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-red?style=flat-square)
![JWT](https://img.shields.io/badge/Auth-JWT-black?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)

> A **production-grade, distributed Flight Management System** built for Beumer Group's Baggage Handling System (BHS) deployment at **Navi Mumbai International Airport (NMIA)**. Designed with a layered architecture, event-driven processing, real-time OpenSky API integration, and JWT-based Role-Based Access Control.

---

## 📑 Table of Contents

- [Project Overview](#-project-overview)
- [Live System Architecture](#-live-system-architecture)
- [Features](#-features)
- [Tech Stack](#-tech-stack)
- [Project Structure](#-project-structure)
- [Setup & Installation](#-setup--installation)
- [Running the System](#-running-the-system)
- [API Reference](#-api-reference)
- [Role-Based Access Control](#-role-based-access-control)
- [System Design & Engineering Decisions](#-system-design--engineering-decisions)
- [Event-Driven Architecture](#-event-driven-architecture)
- [Hybrid Data Strategy](#-hybrid-data-strategy)
- [Performance Considerations](#-performance-considerations)
- [Security Design](#-security-design)
- [Scalability Strategy](#-scalability-strategy)
- [Trade-offs & Design Decisions](#️-trade-offs--design-decisions)
- [Future Enhancements](#-future-enhancements)
- [Observability](#-observability)
- [Why This Project Stands Out](#-why-this-project-stands-out)

---

## 🌐 Project Overview

The **Beumer Group Flight Management System** is an internal operational tool that simulates a real-world **Airport Operational Database (AODB)** — the integration layer that feeds real-time flight data into baggage handling workflows at airport terminals.

The system manages flight schedules across **5 major Indian airports** and **5 airlines**, supports asynchronous flight ingestion via RabbitMQ, enriches flight status data using the **OpenSky Network API**, and enforces strict role-based access for airport staff and administrators.

| Airport | Code | City |
|---------|------|------|
| Navi Mumbai International Airport | NMI | Navi Mumbai |
| Indira Gandhi International Airport | DEL | Delhi |
| Chhatrapati Shivaji Maharaj International Airport | BOM | Mumbai |
| Kempegowda International Airport | BLR | Bangalore |
| Rajiv Gandhi International Airport | HYD | Hyderabad |

| Airline | Code |
|---------|------|
| IndiGo | 6E |
| Akasa Air | QP |
| Emirates | EK |
| Air India | AI |
| Vistara | UK |

---

## 🏗️ Live System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        FRONTEND (SPA)                           │
│              Vanilla JS · Single Page Application               │
│         Airports · Flights · Register User · Dashboard          │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTP / REST
┌──────────────────────────▼──────────────────────────────────────┐
│                    FastAPI (Port 8000)                           │
│         Auth · Airports · Flights · Users · RBAC                │
│    JWT Middleware · Role Guards · Pydantic Validation           │
└──────┬──────────────────────────────────────┬───────────────────┘
       │ Publish                               │ Query / Update
┌──────▼──────────┐                  ┌────────▼───────────────────┐
│   RabbitMQ      │                  │       MySQL Database        │
│  flight_create  │                  │  flights · airports ·       │
│  _queue         │                  │  airlines · users           │
└──────┬──────────┘                  └────────▲───────────────────┘
       │ Consume                               │ Update Status
┌──────▼──────────┐                  ┌────────┴───────────────────┐
│   worker.py     │                  │  opensky_status_updater.py  │
│  Saves flights  │                  │  Real-time status via       │
│  to DB          │                  │  OpenSky Network API        │
└─────────────────┘                  └────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│              flight_publisher.py (Daily Scheduler)              │
│   KNOWN_ROUTES → DailyScheduleGenerator → RabbitMQ Queue       │
│   Sync Live triggered via POST /flights/sync-live (port 8000)   │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│              status_updater.py (Background Task)                │
│   Time-based status transitions every 60 seconds               │
│   Scheduled → Boarding → Departed → Arrived                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## ✨ Features

- **🔐 JWT Authentication** with role-based access (Admin, Staff, Viewer)
- **📬 Async Flight Ingestion** via RabbitMQ — non-blocking, scalable
- **🛫 Daily Schedule Generation** using real Indian airline routes
- **🌍 Real-Time Status Updates** via OpenSky Network API integration
- **📊 Batch Email Reports** — Morning, Afternoon, Evening summaries via Gmail SMTP
- **🏢 Multi-Airport Support** — 5 airports with scoped data access
- **🔄 Automatic Status Transitions** — time-based background updates
- **🧩 SPA Frontend** — clean, responsive Single Page Application
- **🗑️ User Management** — register, list, delete users (admin only)
- **🔒 Credential Emails** — auto-send login details on user registration

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| API Framework | FastAPI 0.115 |
| ORM | SQLAlchemy 2.0 |
| Database | MySQL 8.0 (PyMySQL) |
| Message Broker | RabbitMQ (pika 1.3.2) |
| Authentication | JWT (PyJWT 2.9) |
| Password Hashing | bcrypt 4.2 |
| Email | Gmail SMTP (smtplib) |
| Real-Time Data | OpenSky Network API |
| Frontend | Vanilla JS SPA |
| Config | python-dotenv |
| Validation | Pydantic v2 |

---

## 📁 Project Structure

```
Beumer_Flight_Management_System/
├── backend/
│   ├── app.py                        # FastAPI app, lifespan, seeding, routing
│   ├── flight_publisher.py           # Daily schedule generator + RabbitMQ publisher
│   ├── worker.py                     # RabbitMQ consumer + batch email scheduler
│   ├── opensky_status_updater.py     # Real-time status via OpenSky API
│   ├── config.py                     # Centralized settings
│   ├── .env                          # Environment secrets (gitignored)
│   ├── controllers/
│   │   ├── auth_controller.py        # Login, register, /me endpoints
│   │   ├── airport_controller.py     # Airport CRUD
│   │   └── flight_controller.py      # Flight CRUD with RBAC enforcement
│   ├── core/
│   │   └── database.py               # Singleton DatabaseManager, session scope
│   ├── models/
│   │   ├── models.py                 # ORM models + OOP domain classes
│   │   └── schemas.py                # Pydantic schemas + serializers
│   ├── services/
│   │   ├── auth_service.py           # Auth, JWT, bcrypt, registration
│   │   ├── email_service.py          # Gmail SMTP credential delivery
│   │   ├── service.py                # Business logic + RBAC enforcement
│   │   └── repository.py             # CRUD operations, duplicate prevention
│   └── utils/
│       ├── flight_create_publisher.py # Publishes to flight_create_queue
│       ├── rabbitmq.py               # MessageProducer + MessageConsumer
│       └── status_updater.py         # Background time-based status loop
├── frontend/
│   ├── index.html                    # SPA shell
│   ├── script.js                     # All page logic and routing
│   ├── style.css                     # Styles
│   └── *.jpg / *.png                 # Airport images
└── .gitignore
```

---

## ⚙️ Setup & Installation

### Prerequisites

- Python 3.11+
- MySQL 8.0 (service name: `MySQL80` on Windows)
- RabbitMQ 3.x (with management plugin enabled)
- Git

### 1. Clone the Repository

```bash
git clone https://github.com/Shaambhavi58/Flight_Management_System.git
cd Flight_Management_System
```

### 2. Create Virtual Environment

```bash
python -m venv .venv

# Windows
.\.venv\Scripts\Activate.ps1

# macOS/Linux
source .venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r backend/requirements.txt
```

### 4. Configure Environment Variables

Create `backend/.env`:

```env
# MySQL
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=your_password
MYSQL_DB=flight_management

# JWT
JWT_SECRET=your-secret-key
JWT_ALGORITHM=HS256
JWT_EXPIRY_HOURS=8

# SMTP (Gmail)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_app_password

# RabbitMQ
RABBITMQ_HOST=localhost
RABBITMQ_PORT=5672
RABBITMQ_USER=guest
RABBITMQ_PASS=guest

# OpenSky Network
OPENSKY_USERNAME=your_opensky_username
OPENSKY_PASSWORD=your_opensky_password

# Batch Report Email
BATCH_REPORT_EMAIL=your_email@gmail.com

# AviationStack (optional)
AVIATIONSTACK_KEY=your_key
```

### 5. Create MySQL Database

```sql
CREATE DATABASE flight_management;
```

---

## 🚀 Running the System

Start services in order — **Terminal 1 must be running before Terminal 2 and 3**.

### Terminal 1 — Main Application
```bash
cd Beumer_Flight_Management_System
.\.venv\Scripts\Activate.ps1
cd backend
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

### Terminal 2 — RabbitMQ Worker
```bash
cd Beumer_Flight_Management_System
.\.venv\Scripts\Activate.ps1
cd backend
python worker.py
```

### Terminal 3 — OpenSky Status Updater
```bash
cd Beumer_Flight_Management_System
.\.venv\Scripts\Activate.ps1
cd backend
python opensky_status_updater.py
```

### Access Points

| Service | URL |
|---------|-----|
| Web GUI | http://localhost:8000 |
| API Docs (Swagger) | http://localhost:8000/docs |
| RabbitMQ Management | http://localhost:15672 |

### Default Admin Credentials

```
Username: admin
Password: admin123
```

---

## 📡 API Reference

### Authentication

| Method | Endpoint | Access | Description |
|--------|----------|--------|-------------|
| POST | `/auth/login` | Public | Login and receive JWT token |
| POST | `/auth/register` | Admin only | Register new user |
| GET | `/auth/me` | Authenticated | Get current user info |
| DELETE | `/auth/users/{id}` | Admin only | Delete a user |

### Airports

| Method | Endpoint | Access | Description |
|--------|----------|--------|-------------|
| GET | `/airports` | Authenticated | List all airports |
| GET | `/airports/{id}` | Authenticated | Get airport by ID |
| GET | `/airports/{id}/flights` | Authenticated | Get flights for airport |

### Flights

| Method | Endpoint | Access | Description |
|--------|----------|--------|-------------|
| GET | `/flights` | Authenticated | List flights (scoped by role) |
| GET | `/flights/{id}` | Authenticated | Get flight by ID |
| POST | `/flights` | Admin, Staff | Queue new flight via RabbitMQ |
| PUT | `/flights/{id}` | Admin only | Update flight |
| DELETE | `/flights/{id}` | Admin only | Delete flight |
| DELETE | `/flights/clear-all` | Admin only | Clear all flights |

### Users

| Method | Endpoint | Access | Description |
|--------|----------|--------|-------------|
| GET | `/users` | Admin only | List all users |

---

## 🔑 Role-Based Access Control

| Permission | Admin | Staff | Viewer |
|-----------|-------|-------|--------|
| View all airports | ✅ | ✅ | ✅ |
| View flights (all airports) | ✅ | ❌ | ❌ |
| View flights (own airport) | ✅ | ✅ | ✅ |
| Create flight | ✅ | ✅ (own airport) | ❌ |
| Update flight | ✅ | ❌ | ❌ |
| Delete flight | ✅ | ❌ | ❌ |
| Register users | ✅ | ❌ | ❌ |
| Delete users | ✅ | ❌ | ❌ |
| View all users | ✅ | ❌ | ❌ |

> Staff members are automatically scoped to their assigned airport. Any `airport_id` provided in their request body is overridden by their profile airport.

---

## 🧠 System Design & Engineering Decisions

### Layered Architecture

The backend follows a strict **4-layer architecture** that cleanly separates concerns and enables independent testing, scaling, and maintenance of each layer.

```
HTTP Request
     ↓
┌─────────────────────────────────┐
│     Controller Layer            │  ← Route definitions, auth guards,
│  (auth/airport/flight           │    request validation, HTTP responses
│   _controller.py)               │
└──────────────┬──────────────────┘
               ↓
┌─────────────────────────────────┐
│      Service Layer              │  ← Business logic, RBAC enforcement,
│  (service.py, auth_service.py)  │    data transformation, error handling
└──────────────┬──────────────────┘
               ↓
┌─────────────────────────────────┐
│     Repository Layer            │  ← All database queries, ORM operations,
│  (repository.py)                │    duplicate prevention, joins
└──────────────┬──────────────────┘
               ↓
┌─────────────────────────────────┐
│     Database Layer              │  ← MySQL via SQLAlchemy ORM,
│  (database.py, models.py)       │    connection pooling, session management
└─────────────────────────────────┘
```

**Layer Responsibilities:**

| Layer | Responsibility | Files |
|-------|---------------|-------|
| Controller | HTTP routing, auth dependency injection, response shaping | `*_controller.py` |
| Service | Business rules, RBAC enforcement, orchestration | `service.py`, `auth_service.py` |
| Repository | Pure DB operations, no business logic | `repository.py` |
| Database | ORM models, connection singleton, session scope | `database.py`, `models.py` |

**Benefits of this approach:**
- **Separation of Concerns** — each layer has one clear job
- **Maintainability** — change DB without touching business logic; change rules without touching queries
- **Testability** — each layer can be unit tested independently
- **Scalability** — service layer can be extracted into microservices independently

### Singleton Database Manager

`DatabaseManager` uses the **Singleton pattern** to ensure only one SQLAlchemy engine and session factory exists per process — preventing connection pool exhaustion under load.

### ORM + Domain Classes

Models are defined twice intentionally:
- **ORM Models** (`UserModel`, `FlightModel`) — for database interaction via SQLAlchemy
- **Domain Classes** (`User`, `Flight`) — encapsulated business objects with property validation, enforcing OOP principles required for the training context

---

## ⚡ Event-Driven Architecture

### Why RabbitMQ?

Flight creation is **decoupled from the HTTP response** using RabbitMQ as a message broker. This is the same pattern used in large-scale systems like airline reservation platforms.

```
POST /flights
     ↓
FlightController validates + resolves airport_id
     ↓
publish_flight_create() → RabbitMQ (flight_create_queue)
     ↓ [HTTP 202 Accepted returned immediately]

[Asynchronous]
worker.py consumes message
     ↓
FlightService.create_flight() → MySQL DB
     ↓
BatchStore records flight for email reporting
     ↓
BatchEmailScheduler fires summary email at scheduled time
```

### Benefits of Async Processing

| Benefit | Explanation |
|---------|-------------|
| Non-blocking API | HTTP responds with 202 immediately — user doesn't wait for DB write |
| High throughput | Multiple workers can consume in parallel |
| Fault tolerance | Messages persist in queue even if worker crashes |
| Scalability | Add more workers without changing API layer |
| Decoupling | Publisher and consumer evolve independently |

### Batch Email Reporting

The worker tracks flights per time batch (morning/afternoon/evening) and fires one consolidated email per batch at scheduled clock times:

| Batch | Flight Window | Email Sent At |
|-------|--------------|---------------|
| Morning | 12:00 AM – 11:59 AM | 12:00 PM |
| Afternoon | 12:00 PM – 05:59 PM | 06:00 PM |
| Evening | 06:00 PM – 11:59 PM | 11:59 PM |

---

## 🔄 Hybrid Data Strategy

The system uses a **two-source data strategy** — combining static schedule generation with live API enrichment.

### Source 1: KNOWN_ROUTES (Schedule Generation)

`flight_publisher.py` uses a curated dictionary of real Indian airline routes with accurate flight durations. A `DailyScheduleGenerator` spreads flights realistically across 24 hours with morning/evening peaks, assigns terminals and gates per airline convention, and computes initial statuses based on current time.

**Why not rely solely on a live API?**
- AviationStack free tier: only 100 calls/month
- OpenSky has coverage gaps for newer airports (NMIA)
- KNOWN_ROUTES provides 100% reliable schedule generation offline

### Source 2: OpenSky Network API (Live Status Enrichment)

`opensky_status_updater.py` polls the OpenSky REST API every 60 seconds and updates flight statuses in the DB by matching callsigns to stored flight numbers.

```
OpenSky states/all endpoint
     ↓
Extract: callsign, on_ground, lat, lon, altitude, velocity
     ↓
Normalize callsign: "AIC" → "AI", "IGO" → "6E"
     ↓
Match against DB flight_number
     ↓
Update status: on_ground=True → "Arrived", False → "In Air"
```

### Combined Flow

```
KNOWN_ROUTES → generates full daily schedule (reliable, always available)
     +
OpenSky API  → enriches status with real-world data (when available)
     =
Accurate, resilient flight information board
```

---

## ⚡ Performance Considerations

| Area | Approach | Impact |
|------|----------|--------|
| Flight creation | Async via RabbitMQ | API never blocks on DB write |
| Status updates | Background loop every 60s | Minimal DB load, near-real-time |
| OpenSky polling | 60s interval with try/except | Handles API downtime gracefully |
| DB connections | SQLAlchemy connection pool + `pool_pre_ping` | Prevents stale connection errors |
| Session management | Context manager `session_scope()` | Auto-commit, auto-rollback, auto-close |
| Duplicate prevention | 4-field unique constraint + pre-check | Zero duplicate flights in DB |
| Frontend | Vanilla JS SPA | Zero framework overhead, fast load |
| Token expiry | 8-hour JWT | Balances security with shift-based UX |

---

## 🔐 Security Design

### Authentication & Authorization

```
Login → bcrypt.verify(password, hash) → JWT issued
     ↓
Every request → Bearer token extracted from Authorization header
     ↓
JWT decoded → user_id, role, airport_id extracted
     ↓
Dependency injection → get_current_user() → require_admin() / require_staff_or_admin()
     ↓
Service layer → second RBAC check (defense in depth)
```

### Security Layers

| Layer | Mechanism | Purpose |
|-------|-----------|---------|
| Passwords | bcrypt with salt rounds | Brute-force resistant hashing |
| Tokens | JWT HS256, 8-hour expiry | Stateless auth, short-lived sessions |
| Frontend | Token expiry check on load | Auto-logout when JWT expires |
| API | Role-based dependency guards | Endpoint-level access control |
| Service | Airport scoping for staff/viewer | Data-level access control |
| Secrets | `.env` file | No hardcoded credentials |
| Repository | `.gitignore` on `.env` | Secrets never committed to Git |
| Admin protection | Cannot delete own account | Prevents accidental lockout |

---

## 📊 Scalability Strategy

| Component | Scaling Approach | Details |
|-----------|-----------------|---------|
| FastAPI | Horizontal (multiple instances) | Stateless — add instances behind a load balancer |
| RabbitMQ | Distributed consumers | Multiple `worker.py` instances consume from same queue |
| Worker | Horizontal scaling | `prefetch_count=1` ensures fair dispatch across workers |
| MySQL | Read replicas + indexing | Unique constraints + joinedload queries optimized |
| OpenSky Updater | Independent service | Runs separately, restartable without affecting core |
| Email Scheduler | Thread-based | Daemon thread — doesn't block main worker loop |
| Status Updater | Async background task | FastAPI `asyncio.create_task()` — non-blocking |

---

## ⚖️ Trade-offs & Design Decisions

| Decision | Choice Made | Alternative Considered | Reason |
|----------|------------|----------------------|--------|
| Data source | KNOWN_ROUTES + OpenSky | 100% live API | API rate limits + NMIA coverage gaps |
| Status updates | Polling (60s) | WebSockets | Simpler infra; acceptable latency for airport boards |
| Message broker | RabbitMQ | Direct DB write / Redis | Decoupling, persistence, fault tolerance |
| Frontend | Vanilla JS SPA | React / Vue | Zero build tooling; fast delivery; learning focus |
| Auth | JWT (stateless) | Session-based | Scalable across multiple API instances |
| DB | MySQL (relational) | MongoDB | Structured flight data with relationships |
| ORM | SQLAlchemy | Raw SQL | Type safety, portability, session management |
| Architecture | Monorepo | Microservices | Appropriate for training scope; microservices-ready design |

---

## 🚀 Future Enhancements

### Short Term
- [ ] **WebSockets** — push real-time flight status updates to frontend without polling
- [ ] **Pagination** — for large flight boards (1000+ flights)
- [ ] **Flight search & filter** — by airline, status, terminal, gate
- [ ] **Password change endpoint** — allow users to rotate credentials

### Medium Term
- [ ] **Analytics Dashboard** — flight delay rates, on-time performance, terminal utilization
- [ ] **Baggage Tracking Module** — extend into Beumer BHS integration layer
- [ ] **Multi-language Support** — Hindi + English for Indian airport staff
- [ ] **Dark/Light mode toggle** — frontend UX improvement

### Long Term
- [ ] **Cloud Deployment** — AWS ECS / Azure Container Apps with auto-scaling
- [ ] **Microservices Architecture** — split into Auth, Flights, Publisher, Notifier services
- [ ] **Kubernetes** — container orchestration, health checks, rolling deploys
- [ ] **CI/CD Pipeline** — GitHub Actions → Docker → staging → production
- [ ] **Event Sourcing** — full audit trail of all flight status changes
- [ ] **gRPC** — high-performance inter-service communication

---

## 📈 Observability

### Current Logging

The system uses structured `print`-based logging across all components with consistent prefixes:

```
[App]          → Application lifecycle events
[Seed]         → Database seeding
[Worker]       → RabbitMQ message processing
[BatchStore]   → Email batch accumulation
[BatchEmail]   → Email sending results
[Scheduler]    → Clock-based email triggers
[Publisher]    → Flight publishing events
[OpenSky]      → API fetch results
[StatusUpdater]→ Background status transitions
[Repository]   → Duplicate detection
```

### Key Metrics to Monitor

| Metric | Source | Alert Threshold |
|--------|--------|-----------------|
| Queue depth | RabbitMQ Management UI | > 1000 messages |
| Worker processing rate | Worker logs | < 10 msg/min |
| OpenSky fetch failures | OpenSky logs | > 3 consecutive failures |
| DB connection errors | SQLAlchemy logs | Any error |
| Email send failures | BatchEmail logs | Any failure |
| JWT expiry rate | Auth logs | Spike indicates session issues |

### Recommended Production Upgrade

```
Current:  print() → stdout
Upgrade:  Python logging → Structured JSON → ELK Stack / Datadog
```

```python
# Recommended upgrade pattern
import logging
logger = logging.getLogger(__name__)
logger.info("[Worker] Flight saved", extra={"flight_id": result["id"], "airport": result["airport_id"]})
```

---

## 🏁 Why This Project Stands Out

This is not a CRUD tutorial project. It is a **distributed system** that mirrors real-world airport operational infrastructure.

### Engineering Highlights

| Aspect | Implementation |
|--------|---------------|
| **Distributed Architecture** | 4 independent processes communicating via RabbitMQ and MySQL |
| **Event-Driven Design** | Async flight ingestion with persistent message queuing |
| **Real-Time Integration** | OpenSky Network API enriches live flight status |
| **Production-Grade Security** | JWT + bcrypt + RBAC + `.env` secrets + token expiry |
| **Layered Architecture** | Controller → Service → Repository → DB with clean boundaries |
| **Fault Tolerance** | Workers retry on failure, queues persist across restarts |
| **Dual Data Strategy** | Reliable schedule generation + live API enrichment |
| **Automated Reporting** | Clock-based batch email summaries via Gmail SMTP |
| **Airport Operations Context** | Directly maps to Beumer Group's BHS deployment at NMIA |

### Real-World Relevance

This system is architecturally analogous to **Airport Operational Database (AODB)** systems used by airports worldwide — the integration layer between flight information sources and ground systems like baggage handling, boarding gates, and ground crew dispatch.

Built as part of a **Beumer Group internship project**, this demonstrates understanding of:
- Enterprise software architecture patterns
- Distributed systems and async processing
- Real-time data integration
- Production security practices
- Scalable system design

---

## 📄 License

This project is licensed under the MIT License.

---

## 👩‍💻 Author

**Shaambhavi Sharma**
Trainee — Beumer Group
[GitHub](https://github.com/Shaambhavi58) · Built with FastAPI, RabbitMQ, MySQL, and OpenSky API

---
