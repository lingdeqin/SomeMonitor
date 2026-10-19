# quota-providers Specification

## Purpose

从 OpenCode Go、火山方舟、智谱 GLM、Kimi 等多家 AI coding plan 厂商采集额度使用数据，归一化为统一模型并隔离各家故障，供展示层消费。

## Requirements

### Requirement: 统一额度数据模型
系统 SHALL 将每家厂商的原始返回归一化为统一模型，每个额度窗口包含：窗口类型（5 小时/周/月/会话）、已用量、总量、剩余量、百分比、重置时间；原始端缺失的字段 SHALL 缺省处理而非伪造数值。火山方舟返回的 `session`（会话）窗口 SHALL 归一化为 5 小时窗口类型并以「5 小时」展示。

#### Scenario: 字段齐全的窗口
- **WHEN** 厂商返回某窗口的已用量、总量与重置时间（如火山方舟 Agent Plan 的 5h 窗口）
- **THEN** 归一化结果完整包含已用、总量、百分比与重置时间

#### Scenario: 仅有百分比的窗口
- **WHEN** 厂商只返回百分比而无已用/总量（如火山方舟 Coding Plan）
- **THEN** 归一化结果保留百分比，已用与总量标记为缺省，不显示为 0

#### Scenario: 火山方舟会话窗口归一化为 5 小时
- **WHEN** 火山方舟某计划返回 `session` 标签的额度窗口（如 Coding Plan）
- **THEN** 该窗口归一化为 5 小时窗口类型，卡片上显示为「5 小时」

#### Scenario: 数字以字符串返回
- **WHEN** 厂商返回的数值字段是字符串类型（如 Kimi）
- **THEN** 系统解析为数值参与计算与展示

#### Scenario: 已用量缺失但可推导
- **WHEN** 厂商返回总量与剩余量而无已用量
- **THEN** 系统以「总量 - 剩余量」推导已用量

### Requirement: Provider 列表式配置
config 中 `providers` SHALL 为数组；每项 SHALL 含 `vendor`（厂商标识）与 `visible`（是否显示）字段，并可携带该厂商的原有账号配置；数组顺序 SHALL 决定卡片展示顺序；未出现在列表中的厂商与 `visible: false` 的厂商 SHALL 不被实例化、不采集、不显示；配置为旧字典格式时 SHALL 在界面显示中文迁移提示且不发起采集；无法识别的 `vendor` 值 SHALL 被忽略且不影响其他项。

#### Scenario: 只配置已购套餐的厂商
- **WHEN** providers 列表仅含 ark 与 glm 两项且均为 visible
- **THEN** 应用只采集并显示这两家厂商的卡片，其余厂商不出现

#### Scenario: visible 为 false 时隐藏
- **WHEN** 某厂商配置为 `visible: false`
- **THEN** 该厂商不被采集、不显示卡片

#### Scenario: 列表顺序决定卡片顺序
- **WHEN** providers 列表依次为 kimi、ark
- **THEN** 卡片自上而下依次为 Kimi、火山方舟

#### Scenario: 旧字典格式提示迁移
- **WHEN** config 中 `providers` 仍为按厂商的字典（旧格式）
- **THEN** 界面显示中文提示要求迁移为列表格式，且不发起任何采集

### Requirement: 多厂商采集与故障隔离
系统 SHALL 内置 OpenCode Go、火山方舟、智谱 GLM、Kimi、DeepSeek 五家 Provider，并 SHALL 支持通过新增 Provider 模块扩展厂商；任一厂商的采集失败 SHALL NOT 影响其他厂商的采集与展示。

#### Scenario: 单家接口失败
- **WHEN** 某厂商接口超时或返回错误
- **THEN** 仅该厂商进入错误状态，其余厂商正常展示

#### Scenario: 某厂商未配置凭证
- **WHEN** 某厂商的凭证解析在所有来源均未命中
- **THEN** 该厂商显示中性的「未配置」状态，不产生报错弹窗

### Requirement: 多方式凭证解析
每个 Provider SHALL 按固定优先级解析凭证：配置文件中的显式密钥 > 约定的环境变量 > 本机 CLI 登录态自动发现；命中任一级即停止回退。

#### Scenario: 显式配置优先
- **WHEN** 配置文件与环境变量同时存在某厂商的密钥
- **THEN** 使用配置文件中的密钥

#### Scenario: 回退到 CLI 登录态
- **WHEN** 某厂商无显式密钥与环境变量，但本机存在其 CLI 的登录凭据文件
- **THEN** 系统自动发现并使用该登录态，无需用户手工配置

### Requirement: 火山方舟双通道
火山方舟 Provider SHALL 支持两种采集通道：调用本机 arkcli 子进程（应用内无需配置凭证）与使用 AK/SK 直连火山 OpenAPI（SigV4 签名）；通道选择 SHALL 支持 auto 模式。

#### Scenario: 默认走 arkcli 子进程
- **WHEN** 未配置 AK/SK 且本机 arkcli 可用并已登录
- **THEN** 通过 arkcli 子进程采集额度

#### Scenario: 配置 AK/SK 后走直连
- **WHEN** 配置中提供了火山方舟 AK/SK
- **THEN** 通过 SigV4 签名直连 OpenAPI 采集额度

#### Scenario: arkcli 未登录
- **WHEN** 选择子进程通道但 arkcli 未登录或不可用
- **THEN** 该厂商显示错误状态并给出登录指引

### Requirement: 每厂商多账号
每厂商 SHALL 支持配置多个账号，各账号独立采集、独立成败。

#### Scenario: 同厂商两个账号
- **WHEN** 某厂商配置了两个账号且其中一个密钥失效
- **THEN** 另一账号正常展示，失效账号显示错误状态

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
