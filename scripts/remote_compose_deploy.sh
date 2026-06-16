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

run_deploy() {
  export DOCKER_BUILDKIT=1
  export BUILDKIT_PROGRESS=plain
  export COMPOSE_ANSI=never
  bash scripts/pull_docker_images.sh
  docker compose -f docker-compose.prod.yml up -d --build
}

write_log_line() {
  stdbuf -oL -eL printf '%s\n' "$*" >>"$LOG"
}

case "${1:-foreground}" in
  start)
    if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "Deploy already running (pid $(cat "$PID_FILE"))"
      exit 1
    fi
    rm -f "$EXIT_FILE" "$PID_FILE"
    date -Iseconds >"$STARTED_FILE"
    if [[ -s "$LOG" ]]; then
      write_log_line ""
      write_log_line "=== deploy retry $(date -Iseconds) ==="
    else
      : >"$LOG"
      write_log_line "=== deploy started $(date -Iseconds) ==="
    fi
    (
      set +e
      exec > >(stdbuf -oL -eL tee -a "$LOG") 2>&1
      run_deploy
      code=$?
      echo "$code" >"$EXIT_FILE"
      echo "=== deploy finished exit=${code} $(date -Iseconds) ==="
      exit 0
    ) &
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
  diagnostics)
    echo "log_path=$LOG"
    if [[ -f "$LOG" ]]; then
      echo "log_bytes=$(wc -c <"$LOG" | tr -d ' ')"
    else
      echo "log_bytes=0"
    fi
    if [[ -f "$EXIT_FILE" ]]; then
      echo "exit_code=$(cat "$EXIT_FILE")"
    fi
    if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "pid=$(cat "$PID_FILE") running"
    fi
    docker system df 2>/dev/null || true
    dmesg 2>/dev/null | tail -n 5 | grep -i -E 'oom|killed process' || true
    ;;
  foreground)
    run_deploy
    ;;
  *)
    echo "Usage: $0 {start|status|log [lines]|diagnostics|foreground}" >&2
    exit 2
    ;;
esac
