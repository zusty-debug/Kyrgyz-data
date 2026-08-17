#!/usr/bin/env bash
# Start script for the Telegram bot worker.
# The web service uses start.sh; the worker uses this one.

set -e

cd /app

echo "[bot] $(date -u) — launching Telegram bot"

# Bot needs the DB schema in place; ensure tables exist before starting.
python -m bot.bot
