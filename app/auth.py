"""
Authentication.

Two kinds of keys:
  * MASTER key (env var API_KEY) — the one true admin key, never revocable.
  * USER keys (api_keys table) — issued from /admin.

`require_search_key` is for /api/search and /api/person/... — accepts both.
`require_master_key` is for admin endpoints — master only.

Both deps accept the key via the X-API-Key HEADER or the `api_key` /
`X-API-Key` QUERY PARAMETER so URL-triggered flows (e.g. CSV download from
a web UI button) Just Work without needing programmatic blob plumbing.
"""
import os
import hmac
from datetime import datetime
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from .database import get_db
from .models import APIKey

MASTER_KEY = os.environ.get("API_KEY", "dev-secret-key").strip()


def _ct_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def _pick_supplied(request: Request, header_value: Optional[str]) -> Optional[str]:
    """Header first, then ?api_key=, then ?X-API-Key=."""
    if header_value:
        return header_value
    return (
        request.query_params.get("api_key")
        or request.query_params.get("X-API-Key")
    )


def identify_key(db: Session, supplied: Optional[str]):
    """
    Returns ("master", None) | ("user", APIKey) | (None, None).
    Side-effect: updates last_used for user keys.
    """
    if not supplied:
        return None, None
    s = supplied.strip()
    if MASTER_KEY and _ct_eq(s, MASTER_KEY):
        return "master", None
    row = (
        db.query(APIKey)
        .filter(APIKey.key == s, APIKey.revoked == 0)
        .first()
    )
    if row:
        row.last_used = datetime.utcnow()
        db.commit()
        return "user", row
    return None, None


async def require_search_key(
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    db: Session = Depends(get_db),
):
    """Auth for /api/search and /api/person/... (master OR user)."""
    supplied = _pick_supplied(request, x_api_key)
    kind, row = identify_key(db, supplied)
    if kind is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API Key",
            headers={"WWW-Authenticate": "X-API-Key"},
        )
    return {"kind": kind, "row": row}


async def require_master_key(
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    db: Session = Depends(get_db),
):
    """Auth for /api/admin/* (master only)."""
    supplied = _pick_supplied(request, x_api_key)
    kind, row = identify_key(db, supplied)
    if kind != "master":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Master API key required for this action.",
        )
    return {"kind": kind, "row": row}

