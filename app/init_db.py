"""
Create database tables and the GIN trigram indexes that make ILIKE fast
across hundreds of thousands of Cyrillic rows.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import engine
from app.models import Base


def init_db():
    print("Creating database tables... (if not exist)")
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            conn.commit()
            print("pg_trgm extension enabled.")
        # Create GIN indexes for fast ILIKE on Cyrillic columns.
        # (Pure B-tree indexes don't help ILIKE; we need pg_trgm.)
        with engine.begin() as conn:
            for col in ("name", "region", "city", "address"):
                conn.execute(text(
                    f"CREATE INDEX IF NOT EXISTS idx_people_{col}_trgm "
                    f"ON people USING GIN ({col} gin_trgm_ops)"
                ))
            print("GIN trigram indexes ready on name, region, city, address.")
    except Exception as exc:
        print(f"Note: pg_trgm setup deferred ({type(exc).__name__}: {exc})")

    Base.metadata.create_all(bind=engine)
    print("Tables ready:", ", ".join(sorted(Base.metadata.tables.keys())))


if __name__ == "__main__":
    init_db()
