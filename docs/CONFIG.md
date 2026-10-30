# 配置说明

## 加载顺序

配置按以下顺序合并，后加载的覆盖先加载的：

1. `config/settings.yaml`：默认值。所有阈值、权重、天数、比例都写在这里。
2. `config/local/settings.local.yaml`：本机覆盖。只需写要改的键，不进 Git、不打包。
3. 环境变量 `SA__分组__键`：优先级最高，如 `SA__SCORE__STAR5=86`。

嵌套键用双下划线连接，例如：

```bash
# Windows PowerShell
$env:SA__SCHEDULE__DAILY = "mon-fri 16:00"
$env:SA__DAILY_WATCH__ABS_CHANGE_ALERT = "0.05"

# macOS / Linux
export SA__SCHEDULE__DAILY="mon-fri 16:00"
export SA__DAILY_WATCH__ABS_CHANGE_ALERT="0.05"
```

配置模型禁止未知键：拼错键名会直接报错，不会静默忽略。

## 密钥（只放 `.env`）

复制 `.env.example` 为 `.env` 后填写。`.env` 不进 Git、不进交付包。

| 变量 | 用途 |
| --- | --- |
| `LLM_API_KEY` | OpenAI 兼容接口密钥 |
| `LLM_BASE_URL` | 可选；覆盖 `llm.base_url` |
| `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | 飞书自建应用机器人 |
| `FEISHU_WEBHOOK_URL` / `FEISHU_WEBHOOK_SECRET` | 飞书群自定义机器人 |
| `COMMERCIAL_USERNAME` / `COMMERCIAL_PASSWORD` | 商业数据源（可选） |
| `TUSHARE_TOKEN` | Tushare Pro（可选第二数据源） |
| `SA_LOG_LEVEL` | 日志级别，默认 `INFO` |
| `SA_HOME` | 运行数据根目录，默认项目下 `var/` |

## 运行数据目录

默认 `var/`，可用 `SA_HOME` 指向其他磁盘：

```text
var/
  db/        DuckDB 数据库
  logs/      日志
  cache/     公告 PDF 等缓存
  reports/   周报 Markdown 与图表
  locks/     流水线文件锁
  state/     每日/财报去重状态
```

`var/` 整体不进 Git、不进交付包。

## 主要配置分组

| 分组 | 作用 |
| --- | --- |
| `universe` | 板块范围、ST/退市/次新排除、申万一级排除与重点关注行业 |
| `stage0` | 换手率、日均成交额、停牌天数等粗筛阈值 |
| `veto` | 立案/处罚回溯期、质押比例上限、存贷双高与应收膨胀阈值 |
| `soft_downgrade` | 软降级封顶分与三类扣分规则 |
| `fundamental` | 行业样本下限、历史年数、缺失补全折扣、PEG 兜底、一致预期来源 |
| `momentum` | 过热、回调、缩量、企稳、破位参数与均线窗口 |
| `score` | 五星/四星/证据链分数线 |
| `funnel` | 量化池上限、LLM 池上限、关注名单上限、补充池名额与关键词 |
| `llm` | 模型名、温度、重试、token 预算与估算参数 |
| `schedule` | 时区、周报/每日 cron 表达式、补跑宽限小时数 |
| `daily_watch` | 每日涨跌幅告警阈值 |
| `earnings` | 财报披露前提醒的交易日数 |
| `retention` | 档案与筛选日志保留天数 |
| `tracking` | 跟踪周期与基准指数 |
| `backfill` | 历史回填年数 |
| `data_quality` | 交叉验证最大偏差与标签 |
| `commercial` | 商业数据源开关、提供方、HTTP/SDK 偏好 |
| `ingest` | 采集间隔、重试、回看天数、PDF 与缓存开关 |

完整键名和默认值以 `config/settings.yaml` 为准。

## 常用调整

### 模型

```yaml
# config/local/settings.local.yaml
llm:
  base_url: "https://your-provider.example/v1"
  tier1_model: "your-tier1-model"
  tier2_model: "your-tier2-model"
  temperature: 0
```

`LLM_API_KEY` 仍只放 `.env`。校准要求 `temperature=0`。

### 关注名单与持仓

```bash
cp config/local/watchlist.example.yaml config/local/watchlist.yaml
```

```yaml
holdings:
  - code: "000000"
    name: "示例"
    note: "长期持有"
watchlist:
  - code: "000000"
    name: "示例"
```

关注名单上限由 `funnel.watchlist_max` 控制（默认 20），超过会在启动时报错。

### 行业 PEG 表

`config/industry_peg.yaml` 维护行业 PEG 上限；不在表中的行业使用
`fundamental.default_peg_cap`。

### 调度

```yaml
schedule:
  timezone: Asia/Shanghai
  weekly: "sun 20:00"
  daily: "mon-fri 16:30"
  misfire_grace_hours: 12
```

支持 `mon-fri 16:30`、`sun 20:00`、`sat 09:00` 等形式。修改后重启 `sa serve` 生效。

## 校验配置

```bash
uv run sa doctor
```

配置加载失败时 `doctor` 会原样显示 pydantic 的字段错误，按提示修正即可。