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
系统 SHALL 内置 OpenCode Go、火山方舟、智谱 GLM、Kimi 四家 Provider，并 SHALL 支持通过新增 Provider 模块扩展厂商；任一厂商的采集失败 SHALL NOT 影响其他厂商的采集与展示。

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
