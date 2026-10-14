#!/usr/bin/env bash
set -euo pipefail

PIDFILE=".server.pid"
LOG="server.log"

# Host and port come from config.yaml (server.host / server.port).
read -r HOST PORT < <(uv run python -c "
from xscimon.config import get_config
server = get_config()['server']
print(server['host'], server['port'])
")
URL="http://${HOST}:${PORT}"

if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "Server is already running (PID $(cat "$PIDFILE")) at $URL"
    exit 1
fi

uv run uvicorn xscimon.main:app --host "$HOST" --port "$PORT" >> "$LOG" 2>&1 &
PID=$!
echo "$PID" > "$PIDFILE"

# Wait until the server answers (or give up after ~5s).
for _ in $(seq 1 25); do
    if curl -sf "$URL/health" > /dev/null 2>&1; then
        echo "Server started (PID $PID) listening on $URL"
        echo "Admin UI: $URL/admin — Logs: $LOG"
        exit 0
    fi
    if ! kill -0 "$PID" 2>/dev/null; then
        echo "Server failed to start — check $LOG" >&2
        rm -f "$PIDFILE"
        exit 1
    fi
    sleep 0.2
done

echo "Server started (PID $PID) on $URL but /health has not responded yet — check $LOG" >&2
