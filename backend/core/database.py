"""
core/database.py
=================
DatabaseManager — Singleton DB engine, session factory, and table management.

Uses the Singleton pattern so the entire application shares one SQLAlchemy
engine and one connection pool. This prevents "too many connections" errors
that would occur if each service or request created its own engine.

Key components:
  Base          — DeclarativeBase for all ORM models to inherit from
  _build_mysql_url — reads DB credentials from .env and builds the connection URL
  DatabaseManager  — singleton engine + session factory with context-manager support

Connection string format:
  mysql+pymysql://<user>:<password>@<host>:<port>/<database>
"""

import os
from urllib.parse import quote_plus   # safely encode passwords that contain special characters
from dotenv import load_dotenv

load_dotenv()  # Load .env before reading any os.getenv() calls below

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session, DeclarativeBase
from contextlib import contextmanager  # needed for @contextmanager decorator on session_scope


class Base(DeclarativeBase):
    """
    Base class for all SQLAlchemy ORM models.
    Every ORM model (UserModel, FlightModel, etc.) must inherit from this Base
    so SQLAlchemy can discover them when create_tables() is called.
    """
    pass


def _build_mysql_url() -> str:
    """
    Construct the SQLAlchemy MySQL connection URL from environment variables.
    quote_plus() is used to safely encode passwords containing special characters
    like @, #, or % which would otherwise break the URL format.
    """
    host     = os.getenv("MYSQL_HOST",     "localhost")
    port     = os.getenv("MYSQL_PORT",     "3306")
    user     = os.getenv("MYSQL_USER",     "root")
    password = quote_plus(os.getenv("MYSQL_PASSWORD", ""))  # encode special chars in password
    database = os.getenv("MYSQL_DB",       "flight_management")
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}"


class DatabaseManager:
    """
    Singleton class that manages the SQLAlchemy engine, session factory, and
    table creation/deletion. Only one instance exists for the entire process.

    Singleton is implemented via __new__ with a class-level _instance variable.
    The first call to DatabaseManager() creates the engine and session factory;
    all subsequent calls return the same instance without re-initializing.
    """

    _instance = None  # class-level reference to the single instance

    def __new__(cls, db_url: str = None):
        """Create the singleton instance on first call; return it on subsequent calls."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False  # flag checked in __init__ to skip re-init
        return cls._instance

    def __init__(self, db_url: str = None):
        """Initialize the engine and session factory. Skipped if already initialized."""
        if self._initialized:
            return  # singleton guard — don't reinitialize on repeated calls

        self._db_url = db_url or _build_mysql_url()  # use provided URL or build from .env

        # Create the SQLAlchemy engine.
        # pool_pre_ping=True tests each connection before use — prevents errors from
        # MySQL's 8-hour idle connection timeout killing stale pool connections.
        self._engine = create_engine(
            self._db_url,
            echo=False,           # set True to log all SQL statements (useful for debugging)
            pool_pre_ping=True,   # reconnect if MySQL dropped the idle connection
        )

        # Session factory — creates new sessions on demand.
        # autocommit=False: all changes must be committed explicitly (or via session_scope).
        # autoflush=False:  we flush manually inside session_scope before commit.
        self._SessionFactory = sessionmaker(
            bind=self._engine, autocommit=False, autoflush=False
        )

        self._initialized = True  # mark as initialized so __init__ is a no-op next time

    @property
    def engine(self):
        """Expose the raw SQLAlchemy engine (needed for Base.metadata.create_all)."""
        return self._engine

    def create_tables(self):
        """
        Create all DB tables defined by ORM models that inherit from Base.
        Safe to call on every startup — already-existing tables are skipped.
        """
        Base.metadata.create_all(bind=self._engine)

    def drop_tables(self):
        """
        Drop ALL tables in the database.
        Used for a clean slate in development or testing. DESTRUCTIVE — use with care.
        """
        Base.metadata.drop_all(bind=self._engine)

    def get_session(self) -> Session:
        """Return a raw SQLAlchemy session. Prefer session_scope() for normal use."""
        return self._SessionFactory()

    @contextmanager
    def session_scope(self):
        """
        Context manager that provides a transactional DB session.

        Usage:
            with db.session_scope() as session:
                session.query(...)  # all reads and writes here
            # auto-committed on exit, or rolled back on exception

        Guarantees:
          • Commits on clean exit (no exception)
          • Rolls back on any exception (keeps DB consistent)
          • Always closes the session (returns connection to pool)
        """
        session = self.get_session()  # pull a connection from the pool
        try:
            yield session          # hand session to the caller's with-block
            session.commit()       # persist all changes if no exception was raised
        except Exception:
            session.rollback()     # revert all changes in this transaction on error
            raise                  # re-raise so the caller can handle the exception
        finally:
            session.close()        # always return the connection to the pool

    @classmethod
    def reset(cls):
        """
        Destroy the singleton so a new instance can be created.
        Used in unit tests that need a fresh DB connection between test cases.
        """
        cls._instance = None
