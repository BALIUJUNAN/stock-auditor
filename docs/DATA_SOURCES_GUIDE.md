# 数据源说明

## 总体策略

| 数据 | 主来源 | 备用 / 校验 |
| --- | --- | --- |
| 股票列表、上市日期、板块 | AKShare（交易所列表） | 商业源 |
| 申万行业归属与指数 | AKShare（申万研究） | 商业源 |
| 日线行情、成交量、成交额、换手率 | AKShare（新浪 / 腾讯 / 东财） | 商业源 |
| 财务三表与指标 | AKShare（同花顺 / 东财 / 新浪） | 商业源交叉验证 |
| PE / PB / PS 历史 | AKShare（百度 / 东财） | 商业源 |
| 一致预期 | AKShare（东财 / 同花顺） | 商业源优先 |
| 公告列表与正文 | AKShare（巨潮 / 东财） | 商业源正文 |
| 股权质押 | AKShare（东财） | 商业源 |
| 机构调研 | AKShare（东财） | 商业源 |
| 财报预约披露日期 | AKShare（东财） | 商业源 |

具体接口可用性以 `uv run python scripts/probe_akshare.py` 的探测结果为准。

## AKShare（默认，免费）

- 优点：无需账号，覆盖主要公开数据。
- 限制：接口可能限流、变更或临时不可用；不同来源口径可能不同。
- 采集节流：`ingest.request_interval_seconds`（默认 0.5 秒）、
  `ingest.max_retries`（默认 3 次）与指数退避。
- 公告 PDF 按公告编号缓存到 `var/cache/`，扫描件默认跳过。
- 若接口持续失败，先运行 `sa doctor` 定位；必要时增大请求间隔或稍后重试。

## 商业数据源（可选）

- 由 `commercial.enabled` 开关控制，默认关闭；未购买时系统照常运行。
- 优先 HTTP 接口，其次 Windows 专用 SDK；SDK 不可用时自动降级。
- 用于日线、财务的交叉验证：偏差超过 `data_quality.cross_validation.max_deviation`
  标记“数据存疑”；未配置商业源时标记“未交叉验证”，**不阻断** LLM 审计。
- 购买后把账号密码放 `.env` 的 `COMMERCIAL_USERNAME` / `COMMERCIAL_PASSWORD`，
  并在 `config/local/settings.local.yaml` 中设置：

```yaml
commercial:
  enabled: true
  provider: "your-provider"
  prefer_http: true
```

## Tushare Pro（可选第二来源）

- `pyproject.toml` 中作为可选依赖：`uv sync --extra tushare`。
- 在 `.env` 设置 `TUSHARE_TOKEN`。
- 需要相应积分权限；未配置时系统使用 AKShare。

## 一致预期

- 过渡期使用东财 / 同花顺的盈利预测数据，来源记录在结果中。
- 少于 `fundamental.min_analyst_count`（默认 3）家机构覆盖视为缺失。
- 接入商业源后可切换 `fundamental.consensus_source` 并重新跑校准。

## 数据质量标记

| 标记 | 含义 |
| --- | --- |
| `未交叉验证` | 未配置商业源，无法做第二来源校验 |
| `数据存疑` | 两个来源偏差超过阈值 |
| `质押数据不全` | 拿不到控股股东质押明细，不触发硬 Veto |
| `×0.85` | 缺失字段按规则补全后的折扣 |

## 合规与再分发

- 公开接口数据归各数据提供方所有，请遵守其服务条款与访问频率限制。
- 本系统只面向个人研究，不得转售、批量再分发或用于非法荐股。
- 公告正文仅用于本地审计，不随交付包分发。
- 详见 [DISCLAIMER.md](DISCLAIMER.md)。