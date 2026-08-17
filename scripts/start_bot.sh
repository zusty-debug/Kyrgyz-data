#!/usr/bin/env bash
# start_bot.sh — launches the Telegram bot polling loop AND a tiny HTTP
# healthcheck server on $PORT so Render's web-service healthcheck passes.
#
# Render's free tier does NOT include Background Workers, so we run the bot
# as a regular Web Service. The healthcheck server is minimal — just enough
# to answer GET / with 200 OK so Render keeps the service alive.

set -e
cd /app

PORT="${PORT:-10000}"
echo "[bot] $(date -u) — starting healthcheck HTTP on port ${PORT}"

# 1. Tiny HTTP server (background) — required so Render sees the service as
#    healthy. Without this, Render marks the service as failed and stops it.
python3 - <<PYHTTP &
import http.server, os
PORT = int(os.environ.get("PORT", "10000"))
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/health", "/healthz"):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"bot ok")
        else:
            self.send_response(404)
            self.end_headers()
    def log_message(self, *a, **k): pass
http.server.HTTPServer(("0.0.0.0", PORT), H).serve_forever()
PYHTTP

# 2. The Telegram bot polling loop (foreground — keeps container alive).
echo "[bot] $(date -u) — launching Telegram bot polling loop"
exec python -m bot.bot
