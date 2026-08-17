FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ./app /app/app
COPY ./scripts /app/scripts

# Make sure the start script is executable
RUN chmod +x /app/scripts/start.sh && ls -la /app/scripts/start.sh

# Pre-create data directory
RUN mkdir -p /app/data

EXPOSE 8000

# Run via bash so we never depend on the executable bit
CMD ["bash", "/app/scripts/start.sh"]
