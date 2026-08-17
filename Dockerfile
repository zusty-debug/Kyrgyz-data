FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

# Install Python deps first (cacheable layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the four code packages
COPY ./app        /app/app
COPY ./bot        /app/bot
COPY ./importer   /app/importer
COPY ./scripts    /app/scripts

# Make sure the start scripts are executable
RUN chmod +x /app/scripts/start.sh /app/scripts/start_bot.sh

# Pre-create data directory for the downloaded TXT
RUN mkdir -p /app/data

EXPOSE 8000

# Default CMD runs the API (uvicorn). Render workers override this via startCommand.
CMD ["bash", "/app/scripts/start.sh"]
