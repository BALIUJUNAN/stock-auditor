# stock-auditor

[![CI](https://github.com/BALIUJUNAN/stock-auditor/actions/workflows/ci.yml/badge.svg)](https://github.com/BALIUJUNAN/stock-auditor/actions/workflows/ci.yml)

A 股基本面选股辅助与智能审计系统。以量化筛选打底，用大模型对候选股做结构化审计，
输出带证据链的周报，并在交易日监控核心池异动与财报节点。

> 本项目仅供个人研究，不构成任何投资建议。数据来自公开接口，可能存在缺失、延迟或错误；
> 请独立判断并自行承担投资风险。详见 [docs/DISCLAIMER.md](docs/DISCLAIMER.md)。

## 功能

- **周日流水线 S1~S8**：数据刷新 → Stage 0 → 硬 Veto → 基本面/动量打分 → 漏斗 → LLM 审计 → 周报。
- **每日核心池**：持仓、关注名单与最新周报四星股；四类触发（重大公告、涨跌幅超阈值、动量破位、新硬 Veto）。
- **财报节点**：披露前 7 个交易日提醒；披露后 T+1 全量重算。
- **图表与飞书推送**：周报自动生成 Top 10 得分图（matplotlib PNG，`var/reports/<run_id>.png`），
  自建应用会自动上传图片并附在卡片中；同时支持 `/查`、`/周报`、`/状态`、`/帮助` 与
  “加入关注”“本周忽略”按钮。
- **常驻服务**：单进程运行 APScheduler 与飞书长连接；启动时补跑 12 小时内错过的任务。
- **开机自启**：Windows 注册表、macOS LaunchAgent、Linux systemd user。
- **交付打包**：`sa package` 自动扫描密钥与提示词中的私有数据。

## 环境要求

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- Windows 10/11、macOS 或 Linux
- 可选：飞书自建应用机器人（推荐）或群自定义机器人；任意 OpenAI 兼容大模型接口

## 快速开始

### Windows

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

需要一并回填历史数据、安装开机自启时：

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 -Backfill -Autostart
```

### macOS / Linux

```bash
chmod +x install.sh
./install.sh
```

### 手动安装

```bash
uv sync --frozen
cp .env.example .env          # 填写密钥；.env 不进 Git、不打包
uv run sa init                # 建库并执行迁移
uv run sa init --backfill     # 可选：回填历史数据（可中断续传）
uv run sa doctor              # 环境自检；加 --send-test 会发一张飞书测试卡片
```

## 配置

配置分三层，后者覆盖前者：

1. `config/settings.yaml`：默认阈值、权重、调度时间，所有可调参数都在这里。
2. `config/local/settings.local.yaml`：本机覆盖，不进 Git、不打包。
3. 环境变量 `SA__分组__键`，如 `SA__SCORE__STAR5=86`。

密钥只放在 `.env`（参考 `.env.example`），不要写进 YAML 或代码。
`config/local/` 下的 `feishu.example.yaml`、`watchlist.example.yaml` 是模板，复制为
`feishu.yaml`、`watchlist.yaml` 后填写。

详细说明见 [评分规则](docs/SCORING.md)、[配置说明](docs/CONFIG.md) 与 [飞书配置](docs/FEISHU_SETUP.md)。

## 常用命令

| 命令 | 说明 |
| --- | --- |
| `sa doctor` | 检查 Python、配置、目录、网络接口与飞书通道 |
| `sa init [--backfill]` | 建库、执行迁移；可选回填历史数据 |
| `sa ingest [-c 代码,...]` | 采集行情、财务、估值、公告等数据 |
| `sa run weekly [--refresh] [--resume [RUN_ID]] [--until S8]` | 执行周日流水线并生成周报 |
| `sa run daily [-c 代码,...] [--no-push]` | 扫描核心池异动与财报节点 |
| `sa run earnings [-c 代码,...]` | 执行财报提醒与披露后重算 |
| `sa serve` | 常驻运行定时任务与飞书长连接 |
| `sa bot` | 只启动飞书长连接（调试用） |
| `sa autostart install/uninstall` | 安装或移除开机自启 |
| `sa calibrate` | 对 7 只校准股执行 Tier-1 → Tier-2 对照 |
| `sa report show RUN_ID` | 输出指定运行的周报 Markdown |
| `sa package [-o 路径] [--include-tests] [--force]` | 生成交付压缩包并做安全检查 |

定时时间由 `config/settings.yaml` 的 `schedule` 决定，默认：

```yaml
schedule:
  timezone: Asia/Shanghai
  weekly: "sun 20:00"
  daily: "mon-fri 16:30"
  misfire_grace_hours: 12
```

## 当前限制

- 一致预期采集尚未接通，默认使用历史财务数据；PEG 未评分并按 0 分计入。
- 控股股东及一致行动人质押明细尚不可用，相关硬 Veto 已停用并标记数据不全。
- 公告 PDF 网络下载与真实飞书投递尚需实网验证；扫描版 PDF 不支持 OCR。
- 采集错误会阻止周报继续；公告正文缺失作为警告，候选股正文在模型审计前优先补全。
- 未执行模型审计时只显示量化分、不生成星级；每日核心池不会自动将纯量化分当作最终总分。

## 历史财务数据模式

默认 `fundamental.use_consensus: false`，即使数据库中已有一致预期，也仅使用已披露的历史财务数据计算成长性。成长性按现有缺失降级规则计算并应用折扣；PEG 暂未评分，按 0 分计入估值分项，周报会对受影响股票注明。接入并核实可靠数据源后，可将该项设为 `true`；开启设置本身不会采集或补齐一致预期数据。缺失的行情和财务数据不会自动补齐，刷新异常仍会阻止周报继续。

## 数据、隐私与交付

- `.env`、`config/local/` 下的真实配置、`var/` 运行数据都不进 Git。
- `sa package` 只打包源码、默认配置、迁移、文档与安装脚本；默认排除 `tests/`。
- 打包前会扫描：真实密钥、`sk-` API Key、飞书 Webhook、私钥块，以及
  `config/prompts/` 中的 6 位股票代码与校准股名称。发现问题会中止打包并列出位置。
- 数据源与降级策略见 [docs/DATA_SOURCES_GUIDE.md](docs/DATA_SOURCES_GUIDE.md)。

## 开发

```bash
uv sync
uv run ruff check src tests
uv run pytest
```

CI 在 Windows 与 Ubuntu 上执行同样的检查，并运行一次 `sa package` 验证交付物可生成。

## 许可

[MIT](LICENSE)