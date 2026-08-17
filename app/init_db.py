import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import engine
from app.models import Base

def init_db():
    print("Creating database tables... (if not exist)")
    # pg_trgm is a Postgres extension; ignore on SQLite.
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            conn.commit()
            print("pg_trgm extension enabled.")
    except Exception as exc:
        print(f"Note: skipping pg_trgm ({type(exc).__name__}).")

    Base.metadata.create_all(bind=engine)
    print("Tables ready:", ", ".join(sorted(Base.metadata.tables.keys())))


if __name__ == "__main__":
    init_db()
