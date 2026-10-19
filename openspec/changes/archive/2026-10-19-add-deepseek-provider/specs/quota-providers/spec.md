# Spec Delta

## MODIFIED Requirements

### Requirement: 多厂商采集与故障隔离
系统 SHALL 内置 OpenCode Go、火山方舟、智谱 GLM、Kimi、DeepSeek 五家 Provider，并 SHALL 支持通过新增 Provider 模块扩展厂商；任一厂商的采集失败 SHALL NOT 影响其他厂商的采集与展示。

#### Scenario: 单家接口失败
- **WHEN** 某厂商接口超时或返回错误
- **THEN** 仅该厂商进入错误状态，其余厂商正常展示

#### Scenario: 某厂商未配置凭证
- **WHEN** 某厂商的凭证解析在所有来源均未命中
- **THEN** 该厂商显示中性的「未配置」状态，不产生报错弹窗

## ADDED Requirements

### Requirement: DeepSeek 余额采集
系统 SHALL 通过 DeepSeek 官方余额接口（`GET https://api.deepseek.com/user/balance`，Bearer API Key 鉴权）采集并归一化余额信息：总余额、赠送余额（未过期赠金）、充值余额与币种；金额以字符串返回时 SHALL 解析为数值；缺失或非法字段 SHALL 缺省处理而非置 0；账户持有多种币种（CNY/USD）时 SHALL 选择单一展示币种：账号配置的 `currency` 优先，未配置时取余额最大的一项。

#### Scenario: 字符串金额解析
- **WHEN** 余额接口返回的金额字段为字符串（如 `"110.00"`）
- **THEN** 系统解析为数值 110.0 参与展示

#### Scenario: 多币种默认选择
- **WHEN** `balance_infos` 同时含 CNY 与 USD 两项且 CNY 总余额更大，账号未配置 `currency`
- **THEN** 展示币种为 CNY，展示该项的总余额、赠送余额与充值余额

#### Scenario: 配置指定币种
- **WHEN** 账号配置了 `"currency": "USD"`
- **THEN** 即使另一币种余额更大，也展示 USD 项的余额信息

#### Scenario: 赠送余额缺失
- **WHEN** 响应中 `granted_balance` 缺失或不可解析
- **THEN** 赠送余额保持缺省，余额段不显示赠送金额部分，不显示为 0

### Requirement: DeepSeek 当日消费差值记账
未配置精确通道凭证时，系统 SHALL 以差值记账估算当日已用金额：对同一账号同一币种，将相邻两次采集间余额的下降差值累加为当日消费；余额上升（充值/到账）SHALL 不计为负消费；本地日期切换时 SHALL 归零重新累计；展示币种变化时 SHALL 重置记账基准；记账数据 SHALL 持久化到本地，应用重启后当日累计与观测基准 SHALL 延续。

#### Scenario: 余额下降累加
- **WHEN** 同一账号两次采集中总余额从 110 降至 105
- **THEN** 当日已用金额累加 5

#### Scenario: 充值不计负消费
- **WHEN** 两次采集中总余额从 105 升至 200（充值）
- **THEN** 当日已用金额不变，记账基准更新为 200

#### Scenario: 跨天归零
- **WHEN** 本地日期从某日 23:59 后的首次采集进入次日
- **THEN** 当日已用金额重新从 0 累计，基准取当前余额

#### Scenario: 币种切换重置
- **WHEN** 某账号的展示币种从 CNY 变为 USD
- **THEN** 该账号记账清零并以当前 USD 余额为新基准

#### Scenario: 重启后记账延续
- **WHEN** 应用在当日退出后重启
- **THEN** 恢复当日已累计金额与最后一次观测余额，继续累计

### Requirement: DeepSeek 当日消费精确通道
配置 user_token（控制台登录令牌）后，系统 SHALL 调用 DeepSeek 控制台用量接口（`GET /api/v0/usage/by_api_key/cost`，按本地时区当日零点起算）获取精确当日已用金额并替代估算值展示；精确通道返回鉴权失败或异常时 SHALL 自动回退差值记账估算值，并以灰字提示精确值获取失败及凭证可能过期；精确通道可用期间差值记账 SHALL 仍持续更新。

#### Scenario: token 有效精确展示
- **WHEN** user_token 有效且用量接口返回当日各时段金额
- **THEN** 当日已用金额为各时段金额之和（仅累计与展示币种一致的金额），展示时不带「估算」标注

#### Scenario: token 失效回退估算
- **WHEN** 用量接口返回 token 无效（如 40003 或 401）
- **THEN** 当日已用金额回退为差值记账估算值并标注「估算」，卡片附灰字提示（含重新获取凭证的指引）

#### Scenario: 精确与估算并行
- **WHEN** 精确通道可用期间余额轮询持续进行，随后 token 中途失效
- **THEN** 回退后的估算值当日可用（记账未因精确通道成功而中断）

### Requirement: DeepSeek 凭证解析
DeepSeek 的 API Key SHALL 按账号显式配置 > 环境变量 `DEEPSEEK_API_KEY` 的优先级解析；DeepSeek 无本机 CLI 登录态，两级均未命中时该账号 SHALL 显示「未配置」状态；精确通道凭证 user_token 为可选配置（账号 `user_token` 字段 > 环境变量 `DEEPSEEK_USER_TOKEN`），未配置时当日消费 SHALL 走差值记账估算。

#### Scenario: 环境变量命中
- **WHEN** 账号未配置 api_key 但设置了环境变量 `DEEPSEEK_API_KEY`
- **THEN** 使用环境变量中的 Key 完成采集

#### Scenario: 凭证全未命中
- **WHEN** 账号无显式配置且未设置环境变量
- **THEN** 该账号显示中性的「未配置」状态，不发起余额请求

#### Scenario: 仅配置 API Key
- **WHEN** 账号只配置 api_key、未配置 user_token
- **THEN** 余额信息正常展示，当日已用金额为差值记账估算值
