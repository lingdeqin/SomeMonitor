# Spec Delta

## MODIFIED Requirements

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

## ADDED Requirements

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
