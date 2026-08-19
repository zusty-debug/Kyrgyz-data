"""
FastAPI app: search API + admin UI + file drop-to-import.

Endpoints:
  - GET  /                       public homepage
  - GET  /admin                  admin UI (renders admin.html)
  - GET  /api/search             public search (master or per-user key)
  - GET  /api/person/{id}        single record by 14-digit id
  - GET  /api/admin/stats        admin stats (master key)
  - GET  /api/admin/keys         list per-user keys (master key)
  - POST /api/admin/keys         create per-user key (master key)
  - POST /api/admin/keys/{id}/revoke  revoke per-user key
  - POST /api/admin/import       upload CSV/XLSX/TXT/TSV (master key)
  - GET  /api/admin/imports      recent import log (master key)
"""
import os
import time
import pathlib
import logging
import io
from typing import Optional, List
from datetime import date, datetime

from fastapi import (
    FastAPI, Depends, HTTPException, Query, Request,
    UploadFile, File, BackgroundTasks,
)
from fastapi.security import APIKeyHeader
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import and_, func
from pydantic import BaseModel

import sys
PROJECT_ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.database import engine, get_db
from app.models import Person, APIKey, ImportLog
from app.auth import (
    require_search_key, require_master_key,
)
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

# Lazy-imported importer (avoids loading heavy packages on import).
def _run_importer(file_path: str, source_label: str = "upload") -> dict:
    """Run the TXT/CSV/XLSX importer on file_path, write a log row, return stats."""
    from importer.import_txt import run_import

    started = time.time()
    imported = 0
    skipped = 0

    from importer.import_txt import (
        iter_records, parse_record, _pick_flusher, _get_engine, iter_csv_records,
        iter_xlsx_records,
    )

    eng = _get_engine()
    flush = _pick_flusher(eng, "auto")
    batch_size = 5000

    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".csv":
        token_iter = iter_csv_records(file_path)
    elif ext in (".xlsx", ".xls"):
        token_iter = iter_xlsx_records(file_path)
    else:
        fh = io.open(file_path, "r", encoding="utf-8", errors="replace")
        token_iter = iter_records(fh)

    batch = []
    for tokens in token_iter:
        rec = parse_record(tokens)
        if not rec.is_valid():
            skipped += 1
            continue
        batch.append(rec.to_row())
        if len(batch) >= batch_size:
            imported += flush(eng, batch)
            batch.clear()
    if batch:
        imported += flush(eng, batch)

    return {
        "imported": imported,
        "skipped": skipped,
        "duration_s": int(time.time() - started),
    }


# --- Configuration ---------------------------------------------------------

API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

RATE_LIMIT_PER_MIN = os.environ.get("RATE_LIMIT_PER_MIN", "60")

# --- App & middleware ------------------------------------------------------

app = FastAPI(
    title="People Search",
    description="Search a dataset by name / region / city / address / DOB / id.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url=None,
)

limiter = Limiter(key_func=get_remote_address, default_limits=[f"{RATE_LIMIT_PER_MIN}/minute"])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)


# --- Schemas ---------------------------------------------------------------

class SearchResult(BaseModel):
    id: int
    person_id: str
    name: Optional[str] = None
    region: Optional[str] = None
    city: Optional[str] = None
    address: Optional[str] = None
    dob: Optional[str] = None


class SearchResponse(BaseModel):
    page: int
    limit: int
    count: int
    results: List[SearchResult]


# --- Static pages ----------------------------------------------------------

_STATIC_DIR = pathlib.Path(__file__).parent / "static"

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
def root():
    return FileResponse(str(_STATIC_DIR / "index.html"))


@app.get("/admin", include_in_schema=False)
def admin_page():
    return FileResponse(str(_STATIC_DIR / "admin.html"))


# --- Public search endpoints ----------------------------------------------

@app.get(
    "/api/search",
    response_model=SearchResponse,
    tags=["Search"],
)
@limiter.limit(f"{RATE_LIMIT_PER_MIN}/minute")
def search(
    request: Request,
    db: Session = Depends(get_db),
    auth=Depends(require_search_key),
    name: Optional[str] = Query(None, description="Partial match (case-insensitive)"),
    region: Optional[str] = Query(None, description="Partial match (case-insensitive)"),
    city: Optional[str] = Query(None, description="Partial match (case-insensitive)"),
    address: Optional[str] = Query(None, description="Partial match (case-insensitive)"),
    person_id: Optional[str] = Query(None, description="Exact human ID match"),
    dob: Optional[date] = Query(None, description="Exact YYYY-MM-DD"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    filters = []
    if person_id:
        filters.append(Person.person_id == person_id)
    if name:    filters.append(Person.name.ilike(f"%{name}%"))
    if region:  filters.append(Person.region.ilike(f"%{region}%"))
    if city:    filters.append(Person.city.ilike(f"%{city}%"))
    if address: filters.append(Person.address.ilike(f"%{address}%"))
    if dob:     filters.append(Person.dob == dob)

    query = db.query(Person)
    if filters:
        query = query.filter(and_(*filters))

    count = query.count()
    rows = (
        query.order_by(Person.id)
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )
    return {
        "page": page,
        "limit": limit,
        "count": count,
        "results": [r.to_dict() for r in rows],
    }


@app.get(
    "/api/person/{person_id}",
    response_model=SearchResult,
    tags=["Search"],
    dependencies=[Depends(require_search_key)],
)
def get_person_by_id(
    person_id: str,
    db: Session = Depends(get_db),
):
    p = db.query(Person).filter(Person.person_id == person_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Person not found")
    return p.to_dict()


# --- Admin endpoints -------------------------------------------------------

class StatsResponse(BaseModel):
    total_people: int
    total_imports: int
    last_import: Optional[str] = None
    active_keys: int


@app.get("/api/admin/stats", tags=["Admin"])
def admin_stats(db: Session = Depends(get_db), auth=Depends(require_master_key)):
    total_people = db.query(func.count(Person.id)).scalar() or 0
    total_imports = db.query(func.count(ImportLog.id)).scalar() or 0
    last = db.query(ImportLog).order_by(ImportLog.id.desc()).first()
    active_keys = (
        db.query(func.count(APIKey.id))
        .filter(APIKey.revoked == 0)
        .scalar() or 0
    )
    return {
        "total_people": total_people,
        "total_imports": total_imports,
        "last_import": last.to_dict() if last else None,
        "active_keys": active_keys,
        "master_key_prefix": api_key_header.__class__.__name__[:0] + "***",  # placeholder
    }


class ImportResponse(BaseModel):
    ok: bool
    imported: int
    skipped: int
    duration_s: int
    filename: str
    note: Optional[str] = None


@app.post("/api/admin/import", tags=["Admin"], response_model=ImportResponse)
async def admin_import(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    auth=Depends(require_master_key),
):
    """
    Upload a .txt / .tsv / .csv / .xlsx file. Records merge into the DB;
    unique by person_id, so re-uploading the same file is idempotent.
    """
    name = file.filename or "upload.txt"
    if not name.lower().endswith((".txt", ".tsv", ".csv", ".xlsx", ".xls")):
        raise HTTPException(400, detail="Only .txt, .tsv, .csv, .xlsx, or .xls files are accepted.")

    data_dir = pathlib.Path("/app/data") if pathlib.Path("/app").exists() else pathlib.Path(__file__).parent.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    save_path = data_dir / f"upload_{int(time.time())}_{name}"
    size = 0
    with save_path.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            out.write(chunk)
            size += len(chunk)
            if size > 200 * 1024 * 1024:
                out.close()
                save_path.unlink(missing_ok=True)
                raise HTTPException(413, detail="File too large (200 MB cap).")

    try:
        stats = _run_importer(str(save_path), source_label="upload")
    except Exception as e:
        raise HTTPException(500, detail=f"Import failed: {e}")

    log = ImportLog(
        filename=name,
        source="upload",
        imported=stats["imported"],
        skipped=stats["skipped"],
        duration_s=stats["duration_s"],
        note=f"saved to {save_path.name}, {size} bytes",
    )
    db.add(log)
    db.commit()
    return {"ok": True, "filename": name, **stats}


class KeyCreate(BaseModel):
    label: Optional[str] = None


@app.get("/api/admin/keys", tags=["Admin"])
def list_keys(db: Session = Depends(get_db), auth=Depends(require_master_key)):
    rows = db.query(APIKey).order_by(APIKey.id.desc()).limit(500).all()
    return {"keys": [k.to_dict() for k in rows]}


@app.post("/api/admin/keys", tags=["Admin"])
def create_key(
    body: KeyCreate,
    db: Session = Depends(get_db),
    auth=Depends(require_master_key),
):
    new_key = APIKey.generate()
    row = APIKey(key=new_key, label=body.label or "no-label")
    db.add(row)
    db.commit()
    db.refresh(row)
    out = row.to_dict()
    out["key"] = new_key  # full key returned ONCE on creation
    return out


@app.post("/api/admin/keys/{key_id}/revoke", tags=["Admin"])
def revoke_key(
    key_id: int,
    db: Session = Depends(get_db),
    auth=Depends(require_master_key),
):
    row = db.query(APIKey).filter(APIKey.id == key_id).first()
    if not row:
        raise HTTPException(404, detail="Key not found.")
    row.revoked = 1
    db.commit()
    return {"ok": True, "id": key_id}


@app.get("/api/admin/imports", tags=["Admin"])
def list_imports(db: Session = Depends(get_db), auth=Depends(require_master_key)):
    rows = db.query(ImportLog).order_by(ImportLog.id.desc()).limit(100).all()
    return {"imports": [r.to_dict() for r in rows]}
