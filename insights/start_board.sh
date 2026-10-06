#!/bin/sh
# Hydrocarbon Forge — Insights Board launcher
# Usage: ./start_board.sh [port]
# Serves http://0.0.0.0:<port>/ (default 8901) — projects host on 0.0.0.0 (LAN).
# Logs to logs/board.log
# Reuses a running instance if the port is already serving the board.

cd "$(dirname "$0")"
PORT="${1:-8901}"
mkdir -p logs

if curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
  echo "board already running on port $PORT"
  exit 0
fi

PYTHON="$(command -v python3)"
nohup "$PYTHON" server.py --port "$PORT" >> logs/board.log 2>&1 &
echo $! > logs/board.pid
sleep 1
if curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
  echo "board up: http://127.0.0.1:$PORT/ (pid $(cat logs/board.pid))"
else
  echo "failed to start — see logs/board.log"
  tail -5 logs/board.log
  exit 1
fi
