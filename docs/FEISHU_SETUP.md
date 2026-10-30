# 飞书配置

系统支持两种通道，优先使用自建应用机器人：

| 通道 | 能力 | 需要 |
| --- | --- | --- |
| 自建应用（`app`） | 推送卡片、接收指令与按钮回调 | App ID/Secret、群 `chat_id`、长连接 |
| 群自定义机器人（`webhook`） | 只推送卡片 | Webhook URL；可选签名密钥 |

两种通道共用同一个 `send_card` 接口；配置缺失时自动降级为“未配置”，不会阻断流水线。

## 一、自建应用机器人（推荐）

### 1. 创建应用

1. 打开[飞书开放平台](https://open.feishu.cn/)，进入开发者后台，创建“企业自建应用”。
2. 在“凭证与基础信息”中获取 **App ID** 与 **App Secret**。
3. 在“添加应用能力”中启用**机器人**。
4. 在“事件与回调 → 事件订阅”中选择**使用长连接接收事件**，添加事件：
   - `im.message.receive_v1`（接收消息，用于 `/查` 等指令）
5. 在“事件与回调 → 回调订阅”中同样使用长连接，添加：
   - `card.action.trigger`（卡片按钮回调）
6. 在“权限管理”中开通并发布版本：
   - `im:message`（读取消息）
   - `im:message:send_as_bot`（以机器人身份发消息）
   - 如无法获取群 `chat_id`，可额外开通 `im:chat:readonly` 查询群信息。
7. 将机器人加入一个**只包含你自己的专用群**，并记下群的 `chat_id`。

> 长连接模式不需要公网 URL、不需要 Verification Token，也不需要配置请求地址。
> 若企业管理员限制了应用发布，需要先让管理员审核通过。

### 2. 填写配置

```bash
cp config/local/feishu.example.yaml config/local/feishu.yaml
```

```yaml
channel: app
chat_id: "oc_xxxxxxxxxxxxxxxx"   # 推送目标群
allowed_chat_ids: ["oc_xxxxxxxxxxxxxxxx"]
allowed_user_ids: ["ou_xxxxxxxxxxxxxxxx"]
```

`allowed_chat_ids` / `allowed_user_ids` 留空时**不会响应任何指令**（但仍可推送卡片）。
建议只填专用群与你自己的用户 ID，避免误响应其他群。

在 `.env` 中填写密钥：

```dotenv
FEISHU_APP_ID=cli_xxxxxxxxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### 3. 验证

```bash
uv run sa doctor --send-test
```

通过后启动：

```bash
uv run sa bot       # 只启动长连接，调试用
uv run sa serve     # 常驻：定时任务 + 长连接
```

### 4. 可用指令

| 指令 | 说明 |
| --- | --- |
| `/查 000000` | 即时审计单只股票；每人 10 分钟最多 1 次（示例代码） |
| `/周报` | 查看最近一期周报摘要 |
| `/状态` | 查看系统与数据状态 |
| `/帮助` | 显示指令说明 |

卡片按钮：

- **加入关注**：把股票加入 `config/local/watchlist.yaml` 的关注名单。
- **本周忽略**：本周内不再对该股票的每日告警推送卡片，记录在
  `var/state/ignored.json`，按 ISO 周自动失效。

## 二、群自定义机器人（备用）

1. 在目标群中打开“群设置 → 群机器人 → 添加机器人 → 自定义机器人”。
2. 复制 Webhook 地址；如开启签名校验，同时保存密钥。
3. 配置：

```dotenv
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxx
FEISHU_WEBHOOK_SECRET=xxxxxxxx
```

```yaml
# config/local/feishu.yaml
channel: webhook
```

Webhook 通道只支持推送，不支持指令和按钮回调。

## 常见问题

- **发送失败 99991663 / 99991668**：机器人不在目标群，或 `chat_id` 填错。
- **收不到指令**：未开启长连接事件订阅、未发布权限版本，或 `allowed_*` 未包含当前用户/群。
- **App Secret 泄露**：立即在开放平台重置 Secret，并更新 `.env`。
- **Webhook 泄露**：删除并重建群机器人，更新 `.env`。