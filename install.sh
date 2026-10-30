#!/usr/bin/env bash
# stock-auditor macOS / Linux 安装脚本
# 用法：
#   ./install.sh
#   ./install.sh --backfill --autostart

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

usage() {
    cat <<'EOF'
用法：./install.sh [选项]

  --backfill    安装完成后回填历史数据（可中断续传）
  --autostart   安装开机自启（launchd / systemd user）
  -h, --help    显示本说明
EOF
}

backfill=0
autostart=0
for argument in "$@"; do
    case "$argument" in
        --backfill) backfill=1 ;;
        --autostart) autostart=1 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "未知参数：$argument" >&2; usage; exit 2 ;;
    esac
done

echo "==> 检查 uv"
if ! command -v uv >/dev/null 2>&1; then
    cat >&2 <<'EOF'
未找到 uv。请先安装：
  curl -LsSf https://astral.sh/uv/install.sh | sh
安装后重新打开终端，再执行本脚本。
EOF
    exit 1
fi

echo "==> 安装依赖（uv sync --frozen）"
uv sync --frozen

if [ ! -f .env ]; then
    cp .env.example .env
    echo "==> 已生成 .env；请填写 LLM_API_KEY、飞书等密钥后再运行 sa doctor"
fi

echo "==> 建库并执行迁移"
uv run sa init

if [ "$backfill" -eq 1 ]; then
    echo "==> 回填历史数据（可中断，重复执行会续传）"
    uv run sa init --backfill
fi

echo "==> 检查环境（缺少密钥时只提示，不阻断安装）"
if ! uv run sa doctor; then
    echo "警告：doctor 有未通过项；填好 .env 与 config/local/ 后重新执行：uv run sa doctor" >&2
fi

if [ "$autostart" -eq 1 ]; then
    echo "==> 安装开机自启"
    uv run sa autostart install
fi

cat <<'EOF'

安装完成。常用命令：
  uv run sa doctor                    环境自检
  uv run sa ingest                    采集数据
  uv run sa run weekly --refresh      生成周报
  uv run sa serve                     常驻运行（定时任务 + 飞书）
EOF