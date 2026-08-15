#!/bin/zsh
set -eu
cd "$(dirname "$0")"
PORT="${CADKIT_PORT:-8765}"
URL="http://127.0.0.1:${PORT}/index.html"
python3 -m http.server "$PORT" --bind 127.0.0.1 >/tmp/cadkit-server.log 2>&1 &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT INT TERM
sleep 0.7
open "$URL"
echo "CadKit: $URL"
echo "終了するにはこの画面で Control+C"
wait "$SERVER_PID"