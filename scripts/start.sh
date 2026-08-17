#!/usr/bin/env bash
# Container start: init DB if missing, optional first-boot data fetch,
# then launch uvicorn. Run idempotently.
set -e

cd /app

echo "[start] $(date -u) — initialising DB schema"
python -m app.init_db

# Optional first-boot data fetch from a public URL.
# Only import if the people table is empty (idempotent across restarts).
if [ -n "${DATA_URL:-}" ]; then
  echo "[start] DATA_URL=${DATA_URL}"
  ROW_COUNT=$(python -c "from app.database import engine; from sqlalchemy import text; \
                          print(list(engine.connect().execute(text('SELECT COUNT(*) FROM people')))[0][0])" 2>/dev/null || echo 0)
  if [ "${ROW_COUNT}" = "0" ]; then
    echo "[start] DB empty — downloading TXT from ${DATA_URL}"
    mkdir -p /app/data
    curl -fsSL --retry 5 --retry-delay 5 -o /app/data/data.txt "${DATA_URL}"
    echo "[start] downloaded $(wc -c < /app/data/data.txt) bytes; importing"
    python -m importer.import_txt --file /app/data/data.txt --flush auto --batch 5000 || \
      python -m importer.import_txt --file /app/data/data.txt --flush auto --batch 5000
  else
    echo "[start] people table has ${ROW_COUNT} rows; skipping first-boot import"
  fi
fi

echo "[start] launching uvicorn on 0.0.0.0:${PORT}"
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1 --proxy-headers
