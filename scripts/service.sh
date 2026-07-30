#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$ROOT_DIR/.run"
mkdir -p "$RUN_DIR"

# 固定 port，不可更改。啟動前一律先檢查 port 是否已被占用，
# 絕不允許 uvicorn/vite 因為 port 衝突而悄悄切到別的 port。
BACKEND_PORT=8001
FRONTEND_PORT=5174

usage() {
  cat <<EOF
用法: $0 [--start|--stop|--restart|--status|--logs <backend|frontend>]

  --start     啟動後端(:$BACKEND_PORT)與前端(:$FRONTEND_PORT)
  --stop      停止後端與前端
  --restart   重啟後端與前端
  --status    顯示目前執行狀態
  --logs      顯示指定服務的 log (backend 或 frontend)
EOF
}

# 回傳目前佔用該 port 的所有 PID（可能為空）
pids_on_port() {
  local port="$1"
  lsof -ti ":$port" -sTCP:LISTEN 2>/dev/null || true
}

start_backend() {
  local name="backend"
  local dir="$ROOT_DIR/backend"
  local port="$BACKEND_PORT"
  local pid_file="$RUN_DIR/$name.pid"
  local log_file="$RUN_DIR/$name.log"

  local existing
  existing="$(pids_on_port "$port")"

  if [ -n "$existing" ]; then
    echo "[$name] port $port 已經被占用 (PID: $(echo "$existing" | tr '\n' ' '))，視為已在執行中"
    echo "$existing" | head -1 > "$pid_file"
    return
  fi

  if [ ! -x "$dir/.venv/bin/uvicorn" ]; then
    echo "[$name] 找不到 $dir/.venv，請先執行："
    echo "  cd $dir && python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt"
    return 1
  fi

  if [ -f "$pid_file" ]; then
    rm -f "$pid_file"
  fi

  echo "[$name] 啟動中 (port $port)..."
  (
    cd "$dir"
    nohup ./.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "$port" --reload > "$log_file" 2>&1 &
    echo $! > "$pid_file"
  )

  local waited=0
  while [ -z "$(pids_on_port "$port")" ]; do
    sleep 0.5
    waited=$((waited + 1))
    if [ "$waited" -ge 30 ]; then
      echo "[$name] 啟動逾時：port $port 仍未被占用，請查看 log: $log_file"
      return 1
    fi
  done

  pids_on_port "$port" | head -1 > "$pid_file"
  echo "[$name] 已啟動 (PID $(cat "$pid_file"))，log: $log_file"
}

start_frontend() {
  local name="frontend"
  local dir="$ROOT_DIR/frontend"
  local port="$FRONTEND_PORT"
  local pid_file="$RUN_DIR/$name.pid"
  local log_file="$RUN_DIR/$name.log"

  local existing
  existing="$(pids_on_port "$port")"

  if [ -n "$existing" ]; then
    echo "[$name] port $port 已經被占用 (PID: $(echo "$existing" | tr '\n' ' '))，視為已在執行中"
    echo "$existing" | head -1 > "$pid_file"
    return
  fi

  if [ -f "$pid_file" ]; then
    rm -f "$pid_file"
  fi

  echo "[$name] 啟動中 (port $port)..."
  (
    cd "$dir"
    nohup npm run dev > "$log_file" 2>&1 &
    echo $! > "$pid_file"
  )

  local waited=0
  while [ -z "$(pids_on_port "$port")" ]; do
    sleep 0.5
    waited=$((waited + 1))
    if [ "$waited" -ge 30 ]; then
      echo "[$name] 啟動逾時：port $port 仍未被占用，請查看 log: $log_file"
      return 1
    fi
  done

  pids_on_port "$port" | head -1 > "$pid_file"
  echo "[$name] 已啟動 (PID $(cat "$pid_file"))，log: $log_file"
}

stop_one() {
  local name="$1"
  local port="$2"
  local dir="$3"
  local pid_file="$RUN_DIR/$name.pid"

  local pids
  pids="$(pids_on_port "$port")"

  if [ -z "$pids" ]; then
    echo "[$name] 沒有在執行 (port $port 未被占用)"
    rm -f "$pid_file"
    return
  fi

  echo "[$name] 停止中 (port $port, PID: $(echo "$pids" | tr '\n' ' '))..."
  while read -r pid; do
    [ -z "$pid" ] && continue
    kill -TERM "$pid" 2>/dev/null || true
  done <<<"$pids"

  for _ in $(seq 1 10); do
    if [ -z "$(pids_on_port "$port")" ]; then
      break
    fi
    sleep 0.5
  done

  local remaining
  remaining="$(pids_on_port "$port")"
  if [ -n "$remaining" ]; then
    echo "[$name] 未能正常停止，強制結束"
    while read -r pid; do
      [ -z "$pid" ] && continue
      kill -KILL "$pid" 2>/dev/null || true
    done <<<"$remaining"
  fi

  # 補刀：uvicorn --reload / vite 的上層 wrapper 行程有時不會隨著子行程
  # 一起結束，用專案路徑掃一次殘留的 wrapper，避免累積殭屍行程。
  pkill -f "$dir" 2>/dev/null || true

  rm -f "$pid_file"
  echo "[$name] 已停止"
}

status_one() {
  local name="$1"
  local port="$2"

  local pids
  pids="$(pids_on_port "$port")"
  if [ -n "$pids" ]; then
    echo "[$name] 執行中 (PID: $(echo "$pids" | tr '\n' ' ')), port $port"
  else
    echo "[$name] 未執行 (port $port 未被占用)"
  fi
}

do_start() {
  start_backend
  start_frontend
  echo ""
  echo "後端: http://localhost:$BACKEND_PORT"
  echo "前端: http://localhost:$FRONTEND_PORT"
}

do_stop() {
  stop_one "backend" "$BACKEND_PORT" "$ROOT_DIR/backend"
  stop_one "frontend" "$FRONTEND_PORT" "$ROOT_DIR/frontend"
}

do_status() {
  status_one "backend" "$BACKEND_PORT"
  status_one "frontend" "$FRONTEND_PORT"
}

do_logs() {
  local name="${1:-}"
  if [ -z "$name" ]; then
    echo "用法: $0 --logs <backend|frontend>"
    exit 1
  fi
  local log_file="$RUN_DIR/$name.log"
  if [ ! -f "$log_file" ]; then
    echo "找不到 log: $log_file（服務可能還沒啟動過）"
    exit 1
  fi
  tail -f "$log_file"
}

case "${1:-}" in
  --start)
    do_start
    ;;
  --stop)
    do_stop
    ;;
  --restart)
    do_stop
    do_start
    ;;
  --status)
    do_status
    ;;
  --logs)
    do_logs "${2:-}"
    ;;
  *)
    usage
    exit 1
    ;;
esac
