"""
Database engine — Postgres (production) or SQLite (local demo).
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./mock_data.db")

_is_sqlite = DATABASE_URL.startswith("sqlite")

if _is_sqlite:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        connect_args={"check_same_thread": False},
    )
else:
    # NOTE: no statement_timeout here. On Render's free Postgres, a 3-sec
    # cutoff was killing legitimate ILIKE searches across 165k+ Cyrillic
    # rows, returning 500s. The risk of a runaway query is small; if needed,
    # raise an issue and we'll add timeouts per-endpoint instead.
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
