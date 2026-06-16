#!/usr/bin/env bash
# Run on the ECS host (invoked by GitHub Actions or manually).
# Builds and starts the production stack; writes status for remote polling.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

STATE_DIR="${DEPLOY_STATE_DIR:-/tmp/alldocs-deploy}"
LOG="${STATE_DIR}/compose.log"
PID_FILE="${STATE_DIR}/pid"
EXIT_FILE="${STATE_DIR}/exit"
STARTED_FILE="${STATE_DIR}/started"

mkdir -p "$STATE_DIR"
: >"$LOG"

run_deploy() {
  bash scripts/pull_docker_images.sh
  docker compose -f docker-compose.prod.yml up -d --build
}

case "${1:-foreground}" in
  start)
    if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "Deploy already running (pid $(cat "$PID_FILE"))"
      exit 1
    fi
    rm -f "$EXIT_FILE" "$PID_FILE"
    date -Iseconds >"$STARTED_FILE"
    (
      set +e
      run_deploy
      echo $? >"$EXIT_FILE"
    ) >>"$LOG" 2>&1 &
    echo $! >"$PID_FILE"
    echo "Deploy started (pid $(cat "$PID_FILE")), log: $LOG"
    ;;
  status)
    if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "running"
      exit 0
    fi
    if [[ -f "$EXIT_FILE" ]]; then
      if [[ "$(cat "$EXIT_FILE")" == "0" ]]; then
        echo "succeeded"
      else
        echo "failed"
      fi
      exit 0
    fi
    echo "idle"
    exit 0
    ;;
  log)
    tail -n "${2:-40}" "$LOG" 2>/dev/null || true
    ;;
  foreground)
    run_deploy
    ;;
  *)
    echo "Usage: $0 {start|status|log [lines]|foreground}" >&2
    exit 2
    ;;
esac
