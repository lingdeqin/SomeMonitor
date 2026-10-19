# Proposal

## Why

用户在订阅制 coding plan 之外还持有 DeepSeek 开放平台的**按量付费**账户，希望在同一个悬浮窗里一屏掌握全部 AI 消费：DeepSeek 没有额度窗口（5 小时/周/月），核心关注点是**余额、赠送余额与当日已用金额**。目前悬浮窗只覆盖四家订阅制厂商，DeepSeek 用户只能去网页控制台手动查看。

调研结论（详见 design.md）：DeepSeek **官方仅有余额接口**（`GET /user/balance`，可同时拿到总余额与赠送余额）；**当日消费无官方接口**，社区成熟做法有两条——① 余额差值记账（只用官方接口，估算值）；② 非官方控制台接口（需浏览器 userToken，精确但会过期）。用户已确认**两条路线都要**：差值记帐为零配置默认，可选 userToken 升级为精确值。

## What Changes

- **新增 DeepSeek Provider**（vendor id `deepseek`）：调用官方 `GET https://api.deepseek.com/user/balance` 采集总余额、赠送余额（granted_balance）、充值余额；金额字段为字符串、支持多币种（CNY/USD），按规则选择展示币种。
- **当日已用金额双通道**：
  - 默认（零配置）：**差值记账**——轮询官方余额接口，将余额下降差值累加为当日消费，跨天归零，持久化到本地（App 重启不丢当日累计）；
  - 可选（配置 `user_token` 后）：调用 DeepSeek 控制台非官方接口 `GET /api/v0/usage/by_api_key/cost` 获取**精确**当日消费；token 失效时自动回退差值记账并给出灰字提示（沿用 Kimi 月度额度的降级模式）。
- **卡片新增余额型展示**：DeepSeek 卡片按行显示「余额 / 赠送余额 / 今日已用」，金额带货币符号（¥/$）保留两位小数；估算值标注「（估算）」；字段缺失的行直接省略。
- **配置与文档**：`config.jsonc` 模板、`config.example.jsonc`、README 增补 DeepSeek 条目（凭证表、userToken 获取步骤、已知限制）；`DEEPSEEK_API_KEY` / `DEEPSEEK_USER_TOKEN` 环境变量支持；多账号与其他厂商一致。
- 新增运行时数据文件 `deepseek_ledger.json`（记账持久化，与 config 同目录）。

不修改任何现有厂商行为；未配置 DeepSeek 的用户（配置里没写该厂商）不受任何影响。

## Capabilities

### New Capabilities

（无——DeepSeek 的采集与展示行为分别落在两个既有能力里，不另立新能力。）

### Modified Capabilities

- `quota-providers`: 新增 DeepSeek 厂商——修改「多厂商采集与故障隔离」（四家 → 五家）；新增「DeepSeek 余额采集」「DeepSeek 当日消费双通道」「DeepSeek 凭证解析」三条需求（含字符串金额解析、多币种选择、差值记账规则、userToken 回退等场景）。
- `quota-widget`: 新增「余额型卡片展示」需求——卡片在额度窗口行之外支持余额信息行（余额/赠送余额/今日已用），金额格式、估算标注、缺失省略、以及沿用既有的失败降级展示规则。

## Impact

- **代码**：
  - `app/model.py`：新增 `BalanceInfo` 数据类；`QuotaSnapshot` 增加 `balance` 可选字段。
  - `app/providers/deepseek.py`（新文件）：官方余额接口 + 差值记账 + userToken 精确通道。
  - `app/providers/__init__.py`：注册表加入 `DeepSeekProvider`；`build_providers` 需向 Provider 传递记账数据目录。
  - `app/config.py`：`DEFAULT_CONFIG` 与 `CONFIG_TEMPLATE` 增补 deepseek 条目。
  - `app/ui/card.py`：`VENDOR_NAMES` 加 DeepSeek；卡片渲染余额行（新行组件，模式对齐既有 `FreezeRow`）。
- **测试**：`tests/fixtures/deepseek_balance.json`、`deepseek_usage_cost.json` 等 fixture；`tests/test_provider_deepseek.py`（解析/记账/回退/凭证）；`test_ui_card.py`、`test_model.py`、`test_providers_build.py` 增补用例。
- **文档**：README（厂商清单、凭证表、userToken 获取步骤、已知限制、QA 清单）、`config.example.jsonc`。
- **运行时**：新增 `deepseek_ledger.json`（App 自动生成与维护，与 `state.json` 同目录）。
- **外部依赖**：无新增第三方依赖（沿用 httpx）。
- **非官方接口风险**：`platform.deepseek.com/api/v0/*` 为控制台私有接口，可能随平台改版失效——失败路径已设计为自动降级到估算，不影响余额展示。
