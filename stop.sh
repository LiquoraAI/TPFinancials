#!/usr/bin/env bash
# 停止 TPFinancials 看板服务
set -e
cd "$(dirname "$0")"
PROJECT_ROOT="$(pwd)"
PID_FILE="$PROJECT_ROOT/.server.pid"
PORT=5000

stopped=0

# 1. 用 PID 文件关闭
if [[ -f "$PID_FILE" ]]; then
  PID=$(cat "$PID_FILE")
  if kill -0 "$PID" 2>/dev/null; then
    kill "$PID" 2>/dev/null || true
    sleep 1
    kill -9 "$PID" 2>/dev/null || true
    echo "已停止服务 (PID=$PID)"
    stopped=1
  fi
  rm -f "$PID_FILE"
fi

# 2. 若未通过 PID 停掉，尝试按端口 5000 查找并关闭
if [[ $stopped -eq 0 ]]; then
  # macOS
  if command -v lsof &>/dev/null; then
    PIDS=$(lsof -ti :$PORT 2>/dev/null || true)
    if [[ -n "$PIDS" ]]; then
      echo "$PIDS" | xargs kill -9 2>/dev/null || true
      echo "已停止占用端口 $PORT 的进程"
      stopped=1
    fi
  fi
fi

if [[ $stopped -eq 0 ]]; then
  echo "未发现运行中的看板服务。"
fi
