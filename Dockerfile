FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

# Install Python deps first (cacheable layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the three code packages
COPY ./app        /app/app
COPY ./importer   /app/importer
COPY ./scripts    /app/scripts

# Make sure the start script is executable
RUN chmod +x /app/scripts/start.sh && ls -la /app/scripts/start.sh

# Pre-create data directory for the downloaded TXT
RUN mkdir -p /app/data

EXPOSE 8000

# Run via bash so we never depend on the executable bit
CMD ["bash", "/app/scripts/start.sh"]
