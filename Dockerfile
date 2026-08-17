FROM python:3.11-slim

# --- system deps for psycopg2-binary are bundled in the wheel; nothing else needed.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ./app /app/app
COPY ./scripts /app/scripts

# Pre-create data directory (mounted as persistent disk in render.yaml)
RUN mkdir -p /app/data

EXPOSE 8000

# On every container start:
#  - ensure DB tables exist
#  - if DATA_URL is set AND database is empty, download + import the TXT
#  - then start uvicorn
CMD ["/app/scripts/start.sh"]
