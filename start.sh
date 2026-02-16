#!/usr/bin/env bash
# 启动 TPFinancials 看板服务（后台运行）
set -e
cd "$(dirname "$0")"
PROJECT_ROOT="$(pwd)"
PID_FILE="$PROJECT_ROOT/.server.pid"
LOG_FILE="$PROJECT_ROOT/server.log"

# 若已有 PID 且进程存在，先提示
if [[ -f "$PID_FILE" ]]; then
  OLD_PID=$(cat "$PID_FILE")
  if kill -0 "$OLD_PID" 2>/dev/null; then
    echo "服务已在运行 (PID=$OLD_PID)，访问 http://127.0.0.1:5000"
    echo "若要重启，请先执行: ./stop.sh"
    exit 0
  fi
  rm -f "$PID_FILE"
fi

# 激活虚拟环境（存在时）
if [[ -d "$PROJECT_ROOT/.venv" ]]; then
  source "$PROJECT_ROOT/.venv/bin/activate"
fi

# 后台启动，记录 PID
nohup python server.py >> "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"
echo "已启动 TPFinancials 看板服务 (PID=$(cat "$PID_FILE"))"
echo "访问: http://127.0.0.1:5000"
echo "日志: $LOG_FILE"
