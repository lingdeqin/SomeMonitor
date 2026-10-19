# Design

## Context

现状（与本次改动相关的部分）：`config.jsonc` 的 `providers` 为按厂商的字典（`{"ark": {...}}`），`build_providers` 按固定类顺序实例化全部四家；`AccountCard` 的窗口行为两行布局（首行 名称/进度条/百分比，次行 用量/重置时间），段宽硬编码（52/56px）、卡宽固定 300px；`MainWindow.render_snapshots` 每次刷新**销毁全部卡片重建**再 `setFixedSize`，这是闪烁根因；ark 的 `session` period 映射为 `WindowType.SESSION`（「会话」）；无托盘。详见 proposal.md 与 `openspec/specs/` 两个既有规格。

## Goals / Non-Goals

**Goals:**

- providers 配置切换为列表（`vendor` + `visible`），顺序即卡片顺序，未列出/隐藏的厂商零开销
- 窗口行单行展示，段宽与卡宽可配置
- 行级隐藏/恢复，按卡片粒度持久化
- ark `session` → 「5 小时」
- 刷新原地更新，消除闪烁
- 系统托盘：状态色图标 + 摘要悬停 + 显隐切换 + 菜单

**Non-Goals:**

- 不做旧 dict 配置的自动迁移/转换（用户已确认硬切换，仅提示）
- 不改采集协议、凭证解析链与 `state.json` 既有字段语义
- 不引入图标二进制资源文件（托盘图标用 QPainter 绘制）
- 不做托盘气泡通知（balloon）与开机自启

## Decisions

### D1 providers 列表配置：翻译层放在 `build_providers`，Provider 内部零改动

新 schema：

```jsonc
"providers": [
  { "vendor": "ark", "visible": true, "transport": "auto", "accounts": [ ... ] },
  { "vendor": "glm", "visible": true, "accounts": [ ... ] }
]
```

- `build_providers(config)` 读取列表，按 `vendor` 匹配 Provider 类，**仅实例化 `visible` 不为 false 的项**，并按列表顺序返回；随后 `QuotaService`/渲染顺序自然跟随。
- 每个 Provider 实例拿到的仍是 `{"providers": {<vendor_id>: <该项>}}` 形式的 config 视图（在 `build_providers` 内构造），`BaseProvider.provider_config()/accounts()` 语义不变。**理由**：改动面最小（base.py 与四家 Provider 不动），配置 schema 的用户面与内部面解耦。
- `DEFAULT_CONFIG.providers` 改为含全部四家的列表（`visible: true`），保证无 config.jsonc 时的零配置体验不变。
- **旧格式检测**：`load_config` 后若 `providers` 是 dict，`build_providers` 返回空列表，主窗口显示中文迁移提示卡（「配置格式已升级：providers 需改为数组形式，示例见 README」），不发起采集。选界面提示而非仅控制台日志：用户必须看见。
- 未知 `vendor` 值：跳过该项并在控制台打印一行中文提示，不影响其他项。

### D2 单行窗口行布局：一行 HBox + 固定段宽 + 进度条吃剩余空间

`_build_window_row` 改为一行：`[类型名][进度条(stretch)][百分比][已用/总量][重置时间]`。

- 段宽来自 config `row_layout`（缺省用内置默认）：
  `name_width: 52, percent_width: 48, usage_width: 88, reset_width: 104`；卡宽 `card_width: 380`（原 300）。
- 进度条设 `minimumWidth(32)` 并 stretch=1，占据该行剩余空间；段缺失（无重置时间/无用量）显示空占位保持对齐。
- `MONTHLY_FREEZE`（月度额度徽章行）保持「名称 + 徽章」两段式，名称段沿用 `name_width`。
- 备选「QGridLayout 跨行对齐」被否：行数不定且需独立隐藏，逐行 HBox 更简单，段宽固定已保证视觉对齐。

### D3 窗口类型隐藏：主菜单可勾选开关 + 按类型全局持久化

- `state.json` 存 `hidden_window_types: []`（WindowType value 列表，如 `["monthly"]`）；主窗口右键菜单按**当前数据出现的窗口类型**动态生成「隐藏5 小时 / 隐藏本周 / 隐藏本月」可勾选项（顺序同窗口行排序；月度冻结徽章行不参与），交互与「始终置顶」一致。
- 勾选 → 全局隐藏所有卡片该类型行并写 state + 重渲染；取消勾选 → 恢复。卡片渲染按 `window.type.value in hidden_types` 过滤。
- 行级右键隐藏与「已隐藏的行」恢复子菜单移除：右键任意位置（含行上）统一弹主菜单，开关即所见即所得。
- 修订记录：初版为行级右键 + 按卡片粒度 key（`vendor|account|plan|window_type`）；用户验收（2026-10-16）要求改为与「始终置顶」同形的菜单开关、按类型全局生效，故废弃按卡片粒度方案（该粒度带来的 state 遗留 key 由 `deep_merge` 容忍、代码不再读取）。

### D4 ark session → 5 小时：改映射，不动枚举

- `ark.py` 的 `PERIOD_LABEL_MAP` 将 `"session"` 映射为 `WindowType.FIVE_H`；arkcli 与 openapi 两条解析路径共用该映射，一并生效。
- `WindowType.SESSION` 枚举保留（无其他使用方，但删除是无谓破坏）；排序表中位置不变。
- 边界：同一 item 同时含 `5h` 与 `session`（未观测过的组合）会显示两行「5 小时」——接受，不做去重，遵守「不丢弃数据」原则。

### D5 无闪烁渲染：按 key diff + 卡片原地更新 + 尺寸变化守卫

- `render_snapshots` 重构：以 `vendor|account|plan` 为 key 做 diff——已存在的卡调用新增的 `AccountCard.update_snapshot(snapshot)` 原地更新；新 key 创建插入；消失 key 才 removeWidget + deleteLater。
- `AccountCard` 改为「骨架 + 数据」两段：`__init__` 建标题与行容器骨架，`update_snapshot` 按窗口类型 diff 行并更新进度条/文本/对象名（告警色）。行级同样复用。
- `_lock_size_to_content` 加变化守卫：`totalMinimumSize` 与当前 `sizeHint` 一致时跳过 `setFixedSize`；保留 singleShot 二次锁定（样式 polish 异步）但同样带守卫。
- 渲染过程用 `setUpdatesEnabled(False/True)` 包裹抑制中间态重绘。
- 备选「不 diff、每次重建但冻结窗口尺寸」被否：治标不治本，卡片销毁仍有可见抖动。

### D6 系统托盘：新模块 `app/ui/tray.py`，QPainter 画图标

- `TrayController`：`QSystemTrayIcon` + 右键菜单（显示/隐藏悬浮窗、立即刷新、退出）；`activated(Trigger)` 左键切换 `window.setVisible`。
- 图标：QPainter 绘制圆点，颜色 = 全部可见卡片最紧窗口剩余比例的分级（绿 / 黄≤warn / 红≤danger / 灰=无数据或全错；`MONTHLY_FREEZE` 冻结计 0）。无二进制资源，保持仓库零资产。
- tooltip：逐卡一行「厂商·账号 最紧窗口剩余 xx%」，超过 6 行截断加省略号（Windows tooltip 长度受限）。
- `isSystemTrayAvailable()` 为 False：打一行中文日志，跳过托盘，悬浮窗照常。
- 主窗口 `WM_CLOSE`/退出语义不变（退出即结束进程）；托盘显隐仅运行时状态，不持久化。

### D7 文档与模板

`CONFIG_TEMPLATE`、`config.example.jsonc` 重写为列表格式（含 `visible`、`row_layout`、`card_width`、隐藏行说明）；README 更新配置章节（含旧→新迁移示例）、布局与隐藏行说明、托盘说明、QA 清单补项。

## Risks / Trade-offs

- [单行 5 段挤压进度条] → 段宽与卡宽全部可配置，模板给推荐值；进度条保底 32px。
- [旧 dict 配置升级后窗口「无卡片」] → 迁移提示直接渲染在悬浮窗内，README 提供一步迁移示例。
- [tooltip 长度受限] → 截断 + 省略号策略。
- [行隐藏 key 含 plan_label，计划名变更导致隐藏失效] → 接受（数据优先于记忆）。
- [原地更新引入状态残留（如行从 error 恢复 ok）] → `update_snapshot` 必须全量重建行集合语义（行 diff 含增删），单测覆盖状态切换场景。

## Migration Plan

1. 合入后发布说明标注 **BREAKING**：`providers` 需改为数组（README 附迁移示例）。
2. `state.json` 新增 `hidden_window_types` 字段，旧版本读取时被 `deep_merge` 容忍，无前向破坏。
3. 回滚 = git revert 整个变更；旧代码会忽略 `hidden_window_types` 与新 config 字段（`load_config` 深合并容忍未知键），用户改回 dict 配置即可。

## Open Questions

- 托盘图标除纯色圆点外是否叠加剩余百分比数字——可在实现阶段微调，不影响规格（纯色为底线方案）。
- `row_layout` 各段默认宽度的最终像素值——实现时按 12px 字号实测微调，配置项已保证可调。
