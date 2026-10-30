# 常见问题

## 安装与运行

### 提示找不到 `uv`

按系统安装后重新打开终端：

```powershell
# Windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

也可以直接使用 `uv` 的绝对路径运行 `install.ps1` / `install.sh`。

### `uv sync --frozen` 失败

- 确认 Python 3.12 可用：`uv python list`。
- 删除 `.venv/` 后重试；不要删除 `uv.lock`，依赖版本以锁文件为准。
- 公司网络需要代理时，先设置 `HTTPS_PROXY` / `HTTP_PROXY`。

### Windows 控制台中文乱码

`sa` 在输出被重定向时会自动切到 UTF-8。若交互式窗口仍异常，可先执行：

```powershell
chcp 65001
```

或改用 Windows Terminal / PowerShell 7。

### 为什么 `sa doctor` 有失败项但程序还能跑？

`doctor` 区分必需项与可选项。LLM、飞书未配置时相关检查失败，但采集、量化与本地报告
仍可运行；补跑、定时任务也不受影响。商业数据源是可选插件，未配置不算失败。

## 数据

### 首次 `sa init --backfill` 很慢

全市场 5 年日线、财务、估值、公告需要逐只请求公开接口，受接口限流影响可能持续数小时。
中断后重新执行会从已完成的位置续传，不会从头再来。

### 某些股票没有财务/估值数据

公开接口存在缺失、停牌、次新股或接口临时不可用等情况。系统会：

- 缺失字段按规则补全并打 `×0.85` 折扣；
- 行业样本不足时改用申万一级；
- 商业源未配置时标记“未交叉验证”，而不是“数据存疑”。

### 接口报错或返回空

- 先运行 `sa doctor` 确认新浪、东财、申万接口可访问。
- 公开接口可能限流；调大 `ingest.request_interval_seconds` 或降低采集频率。
- 代理/SSL 拦截会导致请求失败；系统不引入 `truststore`，请让系统证书链保持正常。

### 能删除 `var/` 吗？

可以，但会丢失数据库、报告、每日去重状态与缓存。删除后需重新 `sa init` 并采集。
只想清缓存时，删除 `var/cache/` 即可。

## 大模型

### 没有 `LLM_API_KEY` 会怎样？

周报流水线会跳过模型审计，只生成量化结果，并在周报中标注「未执行模型审计」；
每日/财报任务只做量化重算与卡片推送。
补齐 `.env` 与 `llm.base_url`、`llm.tier1_model`、`llm.tier2_model` 后重新运行即可。

### 如何更换模型？

只改 `config/local/settings.local.yaml` 的 `llm` 分组，不要把密钥写进 YAML。
校准要求 `temperature: 0`；更换模型后建议重新执行 `sa calibrate`。

### 调用费用在哪里看？

每次运行的 token 与费用记录在 `run_log.llm_tokens` / `run_log.llm_cost`，周报也会汇总。

## 飞书

### 卡片没有收到

1. `uv run sa doctor --send-test` 查看具体错误。
2. 确认机器人已在目标群，`chat_id` 正确。
3. Webhook 通道确认 URL 未失效、签名密钥正确。
4. 自建应用确认已发布权限版本。

### 周报里的得分图没有显示

周报会生成 `var/reports/<run_id>.png`，并在推送时尝试上传到飞书主卡片：

- 自建应用（`channel: app`）需要开通图片资源权限（`im:resource`）；
- 群自定义机器人 Webhook 不支持图片上传，只发送文字卡片，PNG 仍保存在本地；
- 上传失败不会阻断文字卡片，原因见日志 `weekly.chart_upload_failed`。

### 指令没有反应

确认使用长连接模式、订阅了 `im.message.receive_v1`，并把你的用户 ID 与群 ID 填进
`allowed_chat_ids` / `allowed_user_ids`。详见 [FEISHU_SETUP.md](FEISHU_SETUP.md)。

### `/查` 提示频率限制

同一用户 10 分钟内只能查询一次；等待提示的秒数后重试。

## 定时任务

### 到点没有执行

- 确认 `sa serve` 正在运行（或已安装开机自启）。
- 确认 `schedule.timezone` 为 `Asia/Shanghai`，cron 表达式正确。
- 任务错过时间但在 `misfire_grace_hours`（默认 12 小时）内，下次启动会补跑；
  已成功的运行不会重复补跑。

### 修改调度时间后不生效

`sa serve` 只在启动时读取配置。修改 `config/settings.yaml` 或本地覆盖后重启服务；
开机自启场景可先 `sa autostart uninstall`，再 `sa autostart install`。

## 打包与交付

### `sa package` 报“发现阻止打包的问题”

按输出的 `[secret]` / `[private]` / `[path]` 定位：

- `secret`：把真实密钥移回 `.env`，或改成占位值；
- `private`：`config/prompts/` 中出现股票代码或校准股名称，需要删除；
- `path`：目标压缩包已存在，加 `--force` 覆盖。

### 交付包里为什么没有 `tests/`？

默认不打包测试代码，避免测试夹具中的假密钥与样例数据进入交付物。需要时加
`--include-tests`，但打包扫描仍会执行。

### 交付包包含哪些内容？

`src/`、`config/`（排除 `config/local/` 真实配置）、`migrations/`、`docs/`（排除内部规划与探测记录）、
`scripts/`、安装脚本、`pyproject.toml`、`uv.lock`、`README`、`LICENSE`、`CHANGELOG`
与 `.env.example`。不包含 `.env`、`var/`、`.venv/`、缓存与数据库文件。