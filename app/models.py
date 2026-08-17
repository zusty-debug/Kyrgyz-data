"""
SQLAlchemy ORM models.
"""
import secrets
from datetime import datetime
from sqlalchemy import Column, Integer, String, Date, DateTime, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Person(Base):
    __tablename__ = "people"

    id = Column(Integer, primary_key=True, index=True)
    person_id = Column(String(32), unique=True, index=True, nullable=False)
    name = Column(String(255), index=True, nullable=True)
    region = Column(String(255), index=True, nullable=True)
    city = Column(String(255), index=True, nullable=True)
    address = Column(String(512), nullable=True)
    dob = Column(Date, index=True, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "person_id": self.person_id,
            "name": self.name,
            "region": self.region,
            "city": self.city,
            "address": self.address,
            "dob": self.dob.isoformat() if self.dob else None,
        }


class APIKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True)
    key = Column(String(64), unique=True, index=True, nullable=False)
    label = Column(String(120), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used = Column(DateTime, nullable=True)
    revoked = Column(Integer, default=0)  # 0 active, 1 revoked (SQLite-friendly)

    @staticmethod
    def generate() -> str:
        # 32-char URL-safe token: easy to paste
        return "mk_" + secrets.token_urlsafe(24)[:30]

    def to_dict(self):
        return {
            "id": self.id,
            "label": self.label,
            "key_prefix": self.key[:8] + "…",
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_used": self.last_used.isoformat() if self.last_used else None,
            "revoked": bool(self.revoked),
        }


class ImportLog(Base):
    __tablename__ = "import_log"

    id = Column(Integer, primary_key=True)
    filename = Column(String(255), nullable=False)
    source = Column(String(64), default="upload")  # upload | firstboot | cli
    imported = Column(Integer, default=0)
    skipped = Column(Integer, default=0)
    duration_s = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    note = Column(Text, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "filename": self.filename,
            "source": self.source,
            "imported": self.imported,
            "skipped": self.skipped,
            "duration_s": self.duration_s,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "note": (self.note or "")[:300],
        }
