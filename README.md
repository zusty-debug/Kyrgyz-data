# Mock Data Search API

A production-shape but deliberately minimal system for searching a large mock
dataset that exists as a single flat TXT file.

```
TXT (huge, multi-line records, no delimiters)
         │
         │   streaming importer (python)
         ▼
PostgreSQL (indexed)
         ▲
         │   queries via SQLAlchemy
         │
FastAPI  │   ● /api/search      (paginated, filtered, case-insensitive, partial)
             ● /api/person/{id} (single record)
             ● API-key auth (header X-API-Key)
             ● rate-limited (SlowAPI)
             ● /docs auto-generated (Swagger UI)
             ● /
```

---

## Layout

```
mock-data-api/
├── app/
│   ├── __init__.py
│   ├── main.py            # FastAPI app, auth, rate limit, /api/search
│   ├── database.py        # SQLAlchemy engine (env-driven, no hardcoded creds)
│   ├── models.py          # ORM model(s) and indexes
│   └── init_db.py         # CREATE TABLE + pg_trgm extension (run once)
├── importer/
│   └── import_txt.py      # streaming TXT → PostgreSQL importer
├── data/
│   └── data.txt           # <-- your TXT goes here
├── docker-compose.yml     # FastAPI + PostgreSQL
├── Dockerfile             # FastAPI image
├── requirements.txt
├── .env.example
└── README.md
```

---

## Quick start (Docker, recommended)

1. **Copy the env template:**
   ```bash
   cp .env.example .env
   # edit POSTGRES_PASSWORD and API_KEY in .env
   ```

2. **Drop your TXT in `data/data.txt`.**

3. **Bring up the stack:**
   ```bash
   docker compose up -d --build
   ```

4. **Create tables (one-time, inside the api container so it talks to the DB):**
   ```bash
   docker compose exec api python -m app.init_db
   ```

5. **Import the TXT (fast COPY mode):**
   ```bash
   docker compose exec api python -m importer.import_txt \
       --file data/data.txt --flush copy --batch 5000
   ```

6. **Open the API:**
   - Swagger UI: http://localhost:8000/docs
   - Health:     http://localhost:8000/

---

## Search API examples

> All calls require the `X-API-Key` header set to your `.env` `API_KEY`.

| Goal                                                | Request                                                   |
| --------------------------------------------------- | --------------------------------------------------------- |
| Exact ID lookup                                     | `/api/search?person_id=20306195500450`                    |
| Calendar date of birth                              | `/api/search?dob=1955-06-03`                              |
| Name contains substring                             | `/api/search?name=Алекс`                                  |
| Region contains substring                           | `/api/search?region=Бишкек`                               |
| Address contains substring                          | `/api/search?address=Советская`                           |
| Combine                                             | `/api/search?name=Александр&region=Бишкек&page=1&limit=20`|
| Single-record lookup                                | `/api/person/{person_id}`                                 |

`limit` is capped at **100**; `page` must be `>= 1`.

Response shape:
```json
{
  "page": 1,
  "limit": 20,
  "count": 1,
  "results": [
    {
      "id": 1,
      "person_id": "20306195500450",
      "name": "Капинос Федор Федорович",
      "region": "Ыссык Кульская",
      "city": null,
      "address": "Тонский р н Каджи сай",
      "dob": "1955-06-03"
    }
  ]
}
```

---

## Important: the TXT parser is format-aware

Based on real raw records from your file, the format is now understood as:

1. **Logical field separator:** `\t` (TAB).
2. **A record is "complete"** when it has both a **14-digit `person_id`** in
   any tab-field **and** a tail of one of:
   - a single tab-field equal to `NULL` (DOB missing), or
   - three tab-fields that look like year, month, day (`YYYY`, `MM`, `DD`).
3. **Records may span multiple physical lines** — the importer buffers tab-
   tokens across lines until the tail is complete.
4. **`person_id`** is the *first* tab-field that exactly matches `^\d{14}$`.
5. **DOB** is normalised to ISO `YYYY-MM-DD`; `NULL` becomes `NULL` in DB.
6. **Name** = the first 1–2 tab-fields, where a second field is absorbed into
   the name only if it ends in a known patronymic suffix (`-ович/-евич/-овна/
   -евна/-кызы/-уулу`) or is a multi-word continuation (org names).
7. **Region** is the longest leading `1–3` word span before `область/обл/район/
   р-н/р н/рн` (longer alternatives preferred so `обл` doesn't eat `область`).
8. **City** is the 1–2 words after `г.\s*`, with a negative lookahead so we
   never pick up a district prefix (`Свердловский р н`) or a street name
   immediately followed by a house number.

The parser was validated against the 16 raw records you supplied and returns
clean values for every one of them.

Malformed records (no person_id) are **counted**, **logged to
`importer/malformed.log`**, but never crash the import.

To re-validate on a slice of the 140 MB file before the full run:

```bash
# Take the first few thousand lines of the real file, run the parser dry, inspect JSON output
head -n 5000 data/data.txt > /tmp/test_slice.txt
docker compose exec api python3 - <<'PY'
import sys; sys.path.insert(0, '/app')
from importer.import_txt import iter_records, parse_record
import io, json
rows = [parse_record(t).__dict__ for t in iter_records(io.open('/tmp/test_slice.txt', 'r', encoding='utf-8'))]
print(f"Parsed {len(rows)} records")
print(json.dumps(rows[:5], ensure_ascii=False, indent=2, default=str))
PY
```

---

## "Will it scale?"

Things that were done on purpose:

| Concern               | Implementation                                                                |
| --------------------- | ------------------------------------------------------------------------------ |
| Memory                | The TXT is **streamed line-by-line**; never `read()`.                           |
| Batch                 | Records accumulate in a `5000`-row buffer and are flushed via `COPY`.           |
| Crash safety          | Each batch is in its own transaction. If the last batch dies mid-way, just re-run the importer — it uses `person_id` unique constraint to avoid duplicates via `ON CONFLICT DO NOTHING`. |
| Indexes               | `person_id` unique, `name`, `region`, `city`, `dob` B-tree indexes.                  |
| Fuzzy text search     | `pg_trgm` extension is enabled at init; recommended for huge text columns.       |
| Query timeouts        | `statement_timeout = 3000 ms` set at the engine level.                          |
| Rate-limit            | SlowAPI 60/min/IP by default; tunable via `RATE_LIMIT_PER_MIN`.                 |
| Pagination            | Offset/limit with a hard cap of 100 rows per request.                          |
| Public exposure       | Postgres is bound to `127.0.0.1:5432` only, not published.                      |

Things to consider **later** (only if needed):

| Symptom                              | Upgrade                                                                       |
| ------------------------------------ | ----------------------------------------------------------------------------- |
| Single-table scans over millions     | Partition `people` by year of `dob` or by region hash.                        |
| Need rich tokenized fuzzy search     | Add GIN trigram indexes on `address` and `name`:                              <br>`CREATE INDEX ON people USING GIN (name gin_trgm_ops);` |
| Need ranking / fuzzy scoring         | Add OpenSearch/Elasticsearch and replicate from Postgres via Debezium etc. |
| Need multilingual (non-Cyrillic)     | Already UTF-8 throughout, but rebuild indexes for new alphabet.               |

### `COPY` vs `INSERT`: which is faster?

For millions of rows: **COPY wins by 10–100×**. We default to `COPY FROM STDIN`
fed from an in-memory `StringIO` so we never re-open the file. If you'd rather
stay fully inside SQLAlchemy for debugging, pass `--flush insert` — it does
batched `INSERT ... ON CONFLICT DO NOTHING`.

---

## Security

* API key is read from the `API_KEY` env var (set in `.env`). Never hardcoded.
* Database credentials are likewise env-driven (`POSTGRES_USER`/`PASSWORD`).
* Reverse-proxy HTTPS in production — suggested:
  * Place a Caddy / Nginx / Traefik in front of `:8000`.
  * Forward standard `X-Forwarded-For` so rate limiting still works.
  * Example (Caddy):
    ```
    api.example.com {
      reverse_proxy api:8000
    }
    ```
* Don't publish port `5432` publicly. The compose file already binds it to
  `127.0.0.1:5432` only.

---

## Useful one-liners

```bash
# Tail import progress while it's running
docker compose exec api tail -f importer/malformed.log

# Restart import from scratch
docker compose exec db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "TRUNCATE people RESTART IDENTITY;"

# Create recommended trigram index manually if not auto-created
docker compose exec db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
  CREATE INDEX IF NOT EXISTS idx_people_name_trgm ON people USING GIN (name gin_trgm_ops);
  CREATE INDEX IF NOT EXISTS idx_people_address_trgm ON people USING GIN (address gin_trgm_ops);
"
```
