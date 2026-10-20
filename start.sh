#!/usr/bin/env bash
# Start backend (port 8000) and frontend (port 5173) together; Ctrl+C stops both.
# Commands come from backend/AGENTS.md and frontend/AGENTS.md (never uvicorn --reload).
set -u
cd "$(dirname "$0")"

BACKEND_URL="http://localhost:8000"
FRONTEND_URL="http://localhost:5173"
pids=()

in_use() {  # listening socket check; a curl probe can't tell (free localhost ports time out on Windows)
  { netstat -an 2>/dev/null || ss -ltn 2>/dev/null; } | grep -E "[:.]$1[[:space:]]" | grep -q LISTEN
}

stop_tree() {  # $1 = pid of a background job; kills it and every child process
  local pid=$1
  kill -0 "$pid" 2>/dev/null || return 0
  if [ -r "/proc/$pid/winpid" ] && command -v taskkill >/dev/null 2>&1; then
    taskkill //T //F //PID "$(cat "/proc/$pid/winpid")" >/dev/null 2>&1
  else
    pkill -TERM -P "$pid" 2>/dev/null
    kill -TERM "$pid" 2>/dev/null
  fi
}

cleanup() {
  trap - INT TERM EXIT
  echo
  echo "Stopping backend and frontend..."
  for pid in "${pids[@]}"; do stop_tree "$pid"; done
  wait 2>/dev/null
  echo "Stopped."
}

for port in 8000 5173; do
  if in_use "$port"; then
    echo "Port $port is already in use; stop that process first." >&2
    exit 1
  fi
done
if [ ! -d frontend/node_modules ]; then
  echo "Frontend not installed: run 'npm install' in frontend/ first." >&2
  exit 1
fi

trap 'cleanup; exit 130' INT TERM
trap cleanup EXIT

(cd backend && exec uv run uvicorn dss.main:app --port 8000) &
pids+=($!)
(cd frontend && exec npm run dev) &
pids+=($!)

both_alive() { kill -0 "${pids[0]}" 2>/dev/null && kill -0 "${pids[1]}" 2>/dev/null; }

ready=0
for _ in $(seq 1 90); do
  both_alive || break
  if in_use 8000 && in_use 5173; then ready=1; break; fi
  sleep 1
done
if [ "$ready" -ne 1 ]; then
  echo "Backend or frontend did not start; see the output above." >&2
  exit 1
fi
echo
echo "Backend:  $BACKEND_URL  (health: $BACKEND_URL/api/health)"
echo "Frontend: $FRONTEND_URL"
echo "Press Ctrl+C to stop both."

# If either process exits, stop the other one too.
while both_alive; do sleep 1; done
echo "A process exited." >&2
exit 1
