"""
DatabaseManager - Handles MySQL connection, session management, and table initialization.
Uses the Singleton pattern so only one instance manages the DB throughout the app.
"""

import os
from urllib.parse import quote_plus
from dotenv import load_dotenv

load_dotenv()  # Load variables from .env file
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session, DeclarativeBase
from contextlib import contextmanager


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""
    pass


def _build_mysql_url() -> str:
    """Build MySQL connection URL from environment variables."""
    host = os.getenv("MYSQL_HOST", "localhost")
    port = os.getenv("MYSQL_PORT", "3306")
    user = os.getenv("MYSQL_USER", "root")
    password = quote_plus(os.getenv("MYSQL_PASSWORD", ""))
    database = os.getenv("MYSQL_DB", "flight_management")
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}"


class DatabaseManager:
    """
    Singleton class that manages the database engine, sessions, and initialization.
    """

    _instance = None

    def __new__(cls, db_url: str = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, db_url: str = None):
        if self._initialized:
            return
        self._db_url = db_url or _build_mysql_url()
        self._engine = create_engine(
            self._db_url,
            echo=False,
            pool_pre_ping=True,
        )
        self._SessionFactory = sessionmaker(
            bind=self._engine, autocommit=False, autoflush=False
        )
        self._initialized = True

    @property
    def engine(self):
        return self._engine

    def create_tables(self):
        """Create all tables defined by ORM models."""
        Base.metadata.create_all(bind=self._engine)

    def drop_tables(self):
        """Drop all tables — used for a fresh start."""
        Base.metadata.drop_all(bind=self._engine)

    def get_session(self) -> Session:
        """Return a new SQLAlchemy session."""
        return self._SessionFactory()

    @contextmanager
    def session_scope(self):
        """Context manager that auto-commits on success and rolls back on error."""
        session = self.get_session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @classmethod
    def reset(cls):
        """Reset the singleton (useful for testing)."""
        cls._instance = None
