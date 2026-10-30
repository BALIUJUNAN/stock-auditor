# 变更记录

## 0.1.0（2026-10-30）

首个可运行版本。

### 数据与量化

- DuckDB 迁移与 `run_log` 运行记录；`sa init --backfill` 可中断续传。
- AKShare 采集：股票池、日线、财务、估值、公告、质押、调研、行业指数。
- 商业数据源可选插件与交叉验证；未配置时标“未交叉验证”，不阻断流程。
- Stage 0、硬 Veto、基本面 40 分、动量 20 分、软降级与总分合成。
- 量化漏斗、补充池与 `quant_check.md`。

### 大模型审计

- OpenAI 兼容客户端：重试、缓存、token/费用统计。
- Tier-1 结构化抽取与 Tier-2 审计打分，输出证据链与风险标签。
- 材料组装、token 预算截断与提示词防泄露测试。
- 7 只校准股对照命令 `sa calibrate`。

### 流水线与推送

- 周日 S1~S8 流水线、文件锁、按 `run_log.step_status` 续跑；`--resume` 续跑最近未成功运行，`--resume RUN_ID` 指定运行。
- LLM 未配置时周报自动降级：跳过模型审计，按量化总分排序输出结果与图表，并标注未审计。
- 每日核心池扫描与四类触发；财报前提醒与披露后 T+1 重算。
- 周报得分图：matplotlib 生成 Top 10 PNG，保存在 `var/reports/<run_id>.png`。
- 飞书主卡片支持图片：自建应用自动上传（`im/v1/images`），Webhook 通道降级为纯文字卡片。
- 飞书卡片周报、告警卡片；自建应用长连接与 Webhook 双通道。
- 飞书指令 `/查`、`/周报`、`/状态`、`/帮助` 与卡片按钮回调。

### 运行与交付

- `sa serve`：APScheduler 定时任务 + 飞书长连接，单进程运行。
- 启动补跑最近 12 小时内错过且未成功的任务。
- `sa autostart install/uninstall`：Windows、macOS、Linux 开机自启。
- `sa package`：交付压缩包，扫描密钥与提示词私有数据。
- `install.ps1` / `install.sh` 安装脚本；Windows + Ubuntu CI。