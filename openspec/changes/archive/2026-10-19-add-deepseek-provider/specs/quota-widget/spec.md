# Spec Delta

## ADDED Requirements

### Requirement: 余额型卡片展示
当账号数据携带余额信息（如 DeepSeek）时，卡片 SHALL 以**单行**展示两段余额信息，从左至右依次为：今日已用、余额；每段由名称与金额组成，金额 SHALL 带货币符号（CNY 为 ¥、USD 为 $）并保留两位小数；来自差值记账的今日已用 SHALL 标注「（估算）」；今日已用缺失时该段 SHALL 省略；余额段金额 SHALL 按赠送余额展示：赠送余额大于 0 时为「充值余额 + 赠送余额」（充值余额缺失时以总余额减赠送余额推导，不小于 0），赠送余额为 0 或缺失时仅为总余额；余额段名称 SHALL 统一为「余额」；余额行 SHALL 遵循既有的采集失败降级展示（沿用上次成功数据并标注失败时间）与灰字提示规则。

#### Scenario: 余额信息行展示（无赠送余额）
- **WHEN** 某 DeepSeek 账号返回总余额 105、赠送余额 0、今日已用 5.23，币种 CNY
- **THEN** 卡片在一行内依次展示今日已用「¥5.23」、余额「¥105.00」

#### Scenario: 余额信息行展示（含赠送余额）
- **WHEN** 某 DeepSeek 账号返回总余额 133、充值余额 105、赠送余额 28、今日已用 5.23，币种 CNY
- **THEN** 卡片在一行内依次展示今日已用「¥5.23」、余额「¥105.00 + ¥28.00」

#### Scenario: 充值余额缺失时推导
- **WHEN** 账号返回总余额 133、赠送余额 28 而充值余额缺失
- **THEN** 余额段展示「余额」「¥105.00 + ¥28.00」（充值余额 = 133 - 28 推导）

#### Scenario: 估算标注
- **WHEN** 今日已用金额来自差值记账估算
- **THEN** 该段金额后标注「（估算）」

#### Scenario: 今日已用缺失省略
- **WHEN** 余额信息中今日已用缺省
- **THEN** 该行仅展示余额段

#### Scenario: 采集失败沿用旧数据
- **WHEN** DeepSeek 采集失败但存在上次成功数据
- **THEN** 卡片继续显示上次成功的余额信息行，并按既有规则标注获取失败时间与旧数据状态

### Requirement: 余额行宽度配置
余额行（余额型卡片的两段信息行）的显示宽度 SHALL 可在 config 中通过 `balance_row_layout` 独立于窗口行配置：`name_width` 为两段名称默认宽（未配置时默认与 `row_layout.name_width` 一致）；按段键 `spent_name_width`/`balance_name_width` SHALL 覆盖各段名称宽，未覆盖的段 SHALL 回退 `name_width`；数值宽度（统一 `value_width` 或按段 `<段>_value_width`，按段优先）设置后该段数值 SHALL 定宽并右对齐，未设置时 SHALL 自适应内容宽度。

#### Scenario: 余额行宽度独立配置
- **WHEN** config 中设置 `balance_row_layout: { "name_width": 80 }` 而 `row_layout.name_width` 保持 52
- **THEN** 余额行的名称段按 80 像素对齐，窗口行的名称段宽度仍为 52 像素，互不影响

#### Scenario: 余额行按段宽度覆盖
- **WHEN** config 中设置 `balance_row_layout: { "name_width": 52, "spent_name_width": 64, "spent_value_width": 88 }`
- **THEN** 今日已用段名称宽 64、数值定宽 88 且右对齐；余额段名称仍为 52、数值自适应
