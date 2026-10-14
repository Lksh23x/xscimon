#!/usr/bin/env bash
set -euo pipefail

PIDFILE=".server.pid"

if [[ ! -f "$PIDFILE" ]]; then
    echo "No PID file found — server may not be running."
    exit 1
fi

PID=$(cat "$PIDFILE")

if ! kill -0 "$PID" 2>/dev/null; then
    echo "Process $PID is not running. Cleaning up stale PID file."
    rm -f "$PIDFILE"
    exit 1
fi

kill "$PID"
rm -f "$PIDFILE"
echo "Server stopped (PID $PID)."
