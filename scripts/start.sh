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

# If DATA_URL is set, always try to import. The importer is idempotent thanks
# to ON CONFLICT (person_id) DO NOTHING in the staging-table flow.
# That means: re-running the full file with an already-partially-populated DB
# will skip existing rows and add only the missing ones.
if [ -n "${DATA_URL:-}" ]; then
  echo "[start] DATA_URL is set"
  ROW_COUNT=$(python -c "from app.database import engine; from sqlalchemy import text; \
                          print(list(engine.connect().execute(text('SELECT COUNT(*) FROM people')))[0][0])" 2>/dev/null || echo 0)
  echo "[start] people table currently has ${ROW_COUNT} rows"
  echo "[start] downloading TXT from ${DATA_URL}"
  mkdir -p /app/data
  python - <<PYEOF || echo "[start] download failed"
import os, sys, urllib.request, time
url = os.environ["DATA_URL"]
out = "/app/data/data.txt"
print(f"[download] GET {url}", flush=True)
for attempt in range(1, 6):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "kyrgyz-data-deploy/1.0"})
        with urllib.request.urlopen(req, timeout=300) as r, open(out, "wb") as f:
            total = 0
            t0 = time.time()
            while True:
                chunk = r.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                total += len(chunk)
            dt = time.time() - t0
        size = os.path.getsize(out)
        print(f"[download] saved {size} bytes in {dt:.1f}s", flush=True)
        sys.exit(0)
    except Exception as e:
        print(f"[download] attempt {attempt}/5 failed: {e}", flush=True)
        time.sleep(5)
sys.exit(1)
PYEOF

  if [ -s /app/data/data.txt ]; then
    SIZE=$(wc -c < /app/data/data.txt)
    echo "[start] downloaded ${SIZE} bytes; importing (idempotent: skips existing rows)"
    python -m importer.import_txt --file /app/data/data.txt --flush auto --batch 5000 \
      || echo "[start] import exited non-zero, continuing"
    ROW_COUNT2=$(python -c "from app.database import engine; from sqlalchemy import text; \
                            print(list(engine.connect().execute(text('SELECT COUNT(*) FROM people')))[0][0])" 2>/dev/null || echo 0)
    echo "[start] people table now has ${ROW_COUNT2} rows"
  else
    echo "[start] data file is empty or missing, skipping import"
  fi
fi

echo "[start] launching uvicorn on 0.0.0.0:${PORT:-8000}"
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1 --proxy-headers
