#!/usr/bin/env bash
# Container start: init DB schema, first-boot import (if DATA_URL set),
# then run uvicorn. Idempotent across restarts.

cd /app

echo "[start] $(date -u) — container PID $$"
echo "[start] environment:"
echo "  PORT=${PORT:-8000}"
echo "  DATA_URL=${DATA_URL:-<unset>}"
echo "  DATABASE_URL=${DATABASE_URL:-<unset>}"

echo "[start] $(date -u) — initialising DB schema"
python -m app.init_db || echo "[start] init_db returned non-zero, continuing"

# Optional first-boot import from a public URL.
# Only triggers when the people table is empty.
if [ -n "${DATA_URL:-}" ]; then
  echo "[start] DATA_URL is set"
  ROW_COUNT=$(python -c "from app.database import engine; from sqlalchemy import text; \
                          print(list(engine.connect().execute(text('SELECT COUNT(*) FROM people')))[0][0])" 2>/dev/null || echo 0)
  echo "[start] people table currently has ${ROW_COUNT} rows"
  if [ "${ROW_COUNT}" = "0" ]; then
    echo "[start] DB empty — downloading TXT from ${DATA_URL}"
    mkdir -p /app/data
    curl -fsSL --retry 5 --retry-delay 5 -o /app/data/data.txt "${DATA_URL}" || echo "[start] download failed, will retry by uvicorn-startup"
    if [ -s /app/data/data.txt ]; then
      echo "[start] downloaded $(wc -c < /app/data/data.txt) bytes; importing"
      python -m importer.import_txt --file /app/data/data.txt --flush auto --batch 5000 || \
        echo "[start] import exited non-zero"
      echo "[start] import finished"
    fi
  fi
fi

echo "[start] launching uvicorn on 0.0.0.0:${PORT:-8000}"
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1 --proxy-headers
