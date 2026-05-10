#!/usr/bin/env bash
# 一键启动 Chat2GO bridge
# 用法：
#   bash ~/chat2go/start.sh                   # 默认 claude 模式
#   bash ~/chat2go/start.sh --ai-mode hermes  # 切换 hermes
set -e
cd "$(dirname "$0")"

# 杀掉已有 bridge 进程，避免重复
pkill -f "chat2go/bridge.py" 2>/dev/null || true
sleep 0.3

# 提示 .env 状态
if [ ! -f .env ]; then
  echo "[start] ⚠️  没有 .env 文件，请先创建并填 API key："
  echo "    echo 'ANTHROPIC_API_KEY=sk-ant-xxxxxx' > ~/chat2go/.env"
  exit 1
fi

# 检查 venv
if [ ! -x .venv/bin/python ]; then
  echo "[start] 初始化 venv..."
  python3 -m venv .venv
  .venv/bin/pip install -q supabase pyyaml httpx pypdf python-docx
fi

echo "[start] 启动 bridge..."
exec .venv/bin/python bridge.py "$@"
