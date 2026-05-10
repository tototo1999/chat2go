#!/usr/bin/env bash
# 一键启动 Chat2GO Agent
set -e
cd "$(dirname "$0")"

# 杀掉已有 bridge 进程，避免重复（兼容老 bridge.py 和新 chat2go_agent）
pkill -f "chat2go/bridge\.py" 2>/dev/null || true
pkill -f "chat2go_agent" 2>/dev/null || true
sleep 0.5

# 提示 .env 状态
if [ ! -f .env ]; then
  echo "[start] ⚠️  没有 .env 文件，请先创建并填 API key："
  echo "    echo 'ANTHROPIC_API_KEY=sk-ant-xxxxxx' > ~/chat2go/.env"
  exit 1
fi

# 检查 venv + 装 agent 包
if [ ! -x .venv/bin/python ]; then
  echo "[start] 初始化 venv..."
  python3 -m venv .venv
fi
if ! .venv/bin/python -c "import chat2go_agent" 2>/dev/null; then
  echo "[start] 安装 chat2go-agent 包..."
  .venv/bin/pip install -q -e ./agent
fi

echo "[start] 启动 chat2go-agent..."
exec .venv/bin/python -m chat2go_agent "$@"
