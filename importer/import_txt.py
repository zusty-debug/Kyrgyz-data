"""
Streaming TXT -> DB importer for the mock data API.

v2 — format-aware, validated against real records:
  - TAB-separated fields
  - Records can span multiple physical lines; the buffer keeps growing
    until the tail signals completion (14-digit person_id + DOB/NULL).
  - person_id matched as `^\\d{14}$` against a single tab-field
  - DOB normalised to ISO YYYY-MM-DD, NULL when missing
  - Name = first tab-field, optionally extended for patronymic / org name
  - Region = longest 1-3 words before `область/обл/район/р-н/р н/рн`
  - City   = 1-2 words after `г.\\s*` with a negative lookahead

Flush strategy:
  * PostgreSQL  → COPY FROM STDIN (10-100× faster than INSERTs)
  * SQLite       → batched INSERT with ON CONFLICT DO NOTHING-equivalent
  * MySQL would fall back too; detection is by url prefix.

Usage:
    python -m importer.import_txt --file data/data.txt --flush auto
"""
from __future__ import annotations

import argparse
import io
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Iterator, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_engine = None
def _get_engine():
    global _engine
    if _engine is None:
        from app.database import engine
        _engine = engine
    return _engine

def _db_kind(engine) -> str:
    return (engine.url.get_backend_name() or "").lower()

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------
RE_PERSON_ID = re.compile(r"^\d{14}$")
RE_REGION = re.compile(
    r"((?:[\w\-]+\s+){1,3}(?:область|обл\.?|район|р-н|р н|рн))",
    re.IGNORECASE,
)
RE_CITY = re.compile(
    r"\bг\.?\s*([А-ЯЁ][а-яёА-ЯЁ\-]+(?:\s+(?![А-ЯЁ][а-яё\-]+\s+(?:р[\s\-.н]*н\b|район\b|\d))[А-ЯЁ][а-яёА-ЯЁ\-]+)?)",
)
PATRONYMIC_SUFFIXES = (
    "ович", "евич", "овна", "евна", "кызы", "уулу",
    "оглы", "кызы", "уулу",
)

# ---------------------------------------------------------------------------
@dataclass
class ParsedRecord:
    person_id: str
    name: Optional[str] = None
    region: Optional[str] = None
    city: Optional[str] = None
    address: Optional[str] = None
    dob: Optional[str] = None  # ISO or None
    raw: str = ""

    def is_valid(self) -> bool:
        return bool(self.person_id)

    def to_row(self):
        return (self.person_id, self.name, self.region, self.city,
                self.address, self.dob)


# ---------------------------------------------------------------------------
def _is_year(s: str) -> bool:
    return len(s) == 4 and s.isdigit() and s[:2] in ("19", "20")
def _is_month(s: str) -> bool:
    return s.isdigit() and 1 <= int(s) <= 12
def _is_day(s: str) -> bool:
    return s.isdigit() and 1 <= int(s) <= 31
def _is_full_date(y, m, d) -> bool:
    return _is_year(y) and _is_month(m) and _is_day(d)
def _looks_name_continuation(tok: str) -> bool:
    s = tok.strip().strip(",")
    if not s:
        return False
    words = s.split()
    if not words:
        return False
    sl = s.lower()
    # Reject anything that looks like a location fragment
    for g in ("обл", "район", "г.", "город", "ул.", "д.", "кв.", "с.",
              "пос.", "б/н", "р-н", "р н", "рн"):
        if g in sl:
            return False
    if words[-1].lower().endswith(PATRONYMIC_SUFFIXES):
        return True
    # Multi-word short, no geo — could be an org-name continuation.
    if 2 <= len(words) <= 3 and len(s) <= 40:
        return True
    return False


# ---------------------------------------------------------------------------
def _record_complete(toks: List[str]) -> bool:
    if not toks:
        return False
    has_pid = any(RE_PERSON_ID.match(t) for t in toks)
    if not has_pid:
        return False
    last = toks[-1].upper()
    if last == "NULL":
        return True
    if len(toks) >= 3 and _is_full_date(toks[-3], toks[-2], toks[-1]):
        return True
    return False


def iter_records(file_obj: io.TextIOBase) -> Iterator[List[str]]:
    buffer: List[str] = []
    for line in file_obj:
        tokens = [t.strip() for t in line.rstrip("\n").rstrip("\r").split("\t")]
        tokens = [t for t in tokens if t]
        if not tokens:
            continue
        buffer.extend(tokens)
        if _record_complete(buffer):
            yield buffer
            buffer = []
    if buffer:
        yield buffer


# ---------------------------------------------------------------------------
def _split_name_location(tokens: List[str]) -> Tuple[List[str], List[str]]:
    if not tokens:
        return [], []
    name = [tokens[0]]
    if len(tokens) >= 2 and _looks_name_continuation(tokens[1]):
        name.append(tokens[1])
        return name, tokens[2:]
    return name, tokens[1:]


def _extract_region(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    m = RE_REGION.search(text)
    return m.group(1).strip() if m else None


def _extract_city(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    m = RE_CITY.search(text)
    return m.group(1).strip() if m else None


def parse_record(tokens: List[str]) -> ParsedRecord:
    tokens = [t.strip() for t in tokens if t.strip()]
    rec = ParsedRecord(person_id="", raw=" | ".join(tokens))
    if not tokens:
        return rec

    pid_idx = None
    for i, t in enumerate(tokens):
        if RE_PERSON_ID.match(t):
            pid_idx = i
            rec.person_id = t
            break
    if pid_idx is None:
        return rec

    if tokens[-1].strip().upper() == "NULL":
        dob_tail_len = 1
        rec.dob = None
    elif (
        len(tokens) >= pid_idx + 4
        and _is_full_date(tokens[-3], tokens[-2], tokens[-1])
    ):
        dob_tail_len = 3
        y, m_, d = tokens[-3], tokens[-2], tokens[-1]
        rec.dob = f"{y}-{int(m_):02d}-{int(d):02d}"
    else:
        dob_tail_len = 0
        rec.dob = None

    head = tokens[:pid_idx]
    name_tokens, loc_pre = _split_name_location(head)
    post_pid_end = len(tokens) - dob_tail_len
    loc_post = tokens[pid_idx + 1:post_pid_end]

    rec.name = " ".join(name_tokens).strip() or None
    full_loc = " ".join(loc_pre + loc_post).strip()
    full_loc = re.sub(r"\s+", " ", full_loc)
    rec.address = full_loc or None
    rec.region = _extract_region(full_loc)
    rec.city = _extract_city(full_loc)
    return rec


# ---------------------------------------------------------------------------
# Flush strategies
# ---------------------------------------------------------------------------
def _flush_copy(engine, batch) -> int:
    """PG COPY FROM STDIN. Uses psycopg2's copy_expert."""
    import psycopg2
    raw_conn = engine.raw_connection()
    try:
        with raw_conn.cursor() as cur:
            buf = io.StringIO()
            for row in batch:
                cells = []
                for v in row:
                    if v is None or v == "":
                        cells.append("\\N")
                    else:
                        s = str(v).replace("\t", " ").replace("\n", " ").replace("\r", " ")
                        cells.append(s)
                buf.write("\t".join(cells) + "\n")
            buf.seek(0)
            cur.copy_expert(
                "COPY people (person_id, name, region, city, address, dob) "
                "FROM STDIN WITH (FORMAT text, NULL '\\N')",
                buf,
            )
        raw_conn.commit()
    except Exception:
        raw_conn.rollback()
        raise
    finally:
        raw_conn.close()
    return len(batch)


def _flush_sqlite(engine, batch) -> int:
    """SQLite bulk insert. Uses INSERT OR IGNORE for idempotence."""
    import sqlite3
    # SQLAlchemy's sqlite engine works but for speed we drop to the raw
    # sqlite3 driver and use executemany.
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=OFF")
        cur.executemany(
            "INSERT OR IGNORE INTO people (person_id, name, region, city, address, dob) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            batch,
        )
        raw.commit()
    finally:
        raw.close()
    return len(batch)


def _flush_insert_orm(engine, batch) -> int:
    """Generic SQLAlchemy INSERT (works for any backend)."""
    from sqlalchemy import text
    rows = [
        {"person_id": r[0], "name": r[1], "region": r[2],
         "city": r[3], "address": r[4], "dob": r[5]}
        for r in batch
    ]
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO people (person_id, name, region, city, address, dob) "
                "VALUES (:person_id, :name, :region, :city, :address, :dob)"
            ),
            rows,
        )
    return len(rows)


def _pick_flusher(engine, mode: str):
    kind = _db_kind(engine)
    if mode == "auto":
        if kind == "postgresql":
            return _flush_copy
        if kind == "sqlite":
            return _flush_sqlite
        return _flush_insert_orm
    if mode == "copy":
        return _flush_copy
    if mode == "sqlite":
        return _flush_sqlite
    if mode == "insert":
        return _flush_insert_orm
    raise ValueError("unknown flush mode: " + mode)


# ---------------------------------------------------------------------------
def run_import(
    file_path: str,
    batch_size: int = 5000,
    flush_mode: str = "auto",
    log_every: int = 5000,
    malformed_log: str = "importer/malformed.log",
):
    eng = _get_engine()
    flush = _pick_flusher(eng, flush_mode)
    print(f"DB backend: {_db_kind(eng)}  flush: {flush.__name__}  "
          f"file: {file_path}  batch: {batch_size}")
    start = time.time()
    imported = 0
    skipped = 0
    batch = []

    os.makedirs(os.path.dirname(malformed_log) or ".", exist_ok=True)
    bad = open(malformed_log, "w", encoding="utf-8")
    try:
        with io.open(file_path, "r", encoding="utf-8", errors="replace") as fh:
            for tokens in iter_records(fh):
                rec = parse_record(tokens)
                if not rec.is_valid():
                    skipped += 1
                    bad.write(rec.raw + "\n---\n")
                    continue
                batch.append(rec.to_row())
                if len(batch) >= batch_size:
                    imported += flush(eng, batch)
                    batch.clear()
                    if imported % log_every == 0:
                        elapsed = time.time() - start
                        rate = imported / max(elapsed, 0.001)
                        print(f"  imported={imported:,}  skipped={skipped:,}  "
                              f"rate={rate:,.0f}/s")
            if batch:
                imported += flush(eng, batch)
    finally:
        bad.close()

    elapsed = time.time() - start
    print("-" * 50)
    print(f"DONE in {elapsed:.1f}s")
    print(f"  imported         : {imported:,}")
    print(f"  skipped/malformed: {skipped:,}")
    print(f"  malformed log    : {malformed_log}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default="data/data.txt")
    parser.add_argument("--batch", type=int, default=5000)
    parser.add_argument(
        "--flush",
        choices=["auto", "copy", "sqlite", "insert"],
        default="auto",
        help="auto picks the best strategy based on the DB backend.",
    )
    args = parser.parse_args()
    run_import(args.file, batch_size=args.batch, flush_mode=args.flush)


if __name__ == "__main__":
    main()
