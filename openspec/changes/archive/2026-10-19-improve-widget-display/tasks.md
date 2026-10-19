# Tasks

## 1. 配置层：providers 列表格式

- [x] 1.1 `app/config.py`：`DEFAULT_CONFIG.providers` 改为含全部四家的数组（每项含 `vendor`/`visible`/账号字段），`CONFIG_TEMPLATE` 同步重写为带中文注释的列表模板；验证 `tests/test_config.py` 新增/更新用例通过（默认配置为列表、模板可被 `parse_jsonc` 解析）
- [x] 1.2 `app/providers/__init__.py`：`build_providers` 按列表解析——`visible: false` 或未列出则不实例化、数组顺序即返回顺序、未知 `vendor` 跳过并打印中文提示；为每家构造 `{"providers": {vendor: 项}}` 的 config 视图（`BaseProvider` 接口不变）；新增辅助函数（如 `providers_config_error(config)`）在检测到旧 dict 格式时返回中文迁移提示；验证 `tests/test_provider_*` 适配后全绿 + 新增用例（仅列两家只建两家、顺序保持、dict 返回提示文案）
- [x] 1.3 `app/ui/window.py` + `app/main.py`：providers 为空且存在迁移提示时，悬浮窗显示中文迁移提示（不发起采集、不显示「加载中」）；验证离屏单测：dict 配置下窗口渲染提示文案且不调用采集

## 2. Provider 层：ark「会话」→「5 小时」

- [x] 2.1 `app/providers/ark.py`：`PERIOD_LABEL_MAP` 中 `"session"` 改映射 `WindowType.FIVE_H`；更新 `tests/test_provider_ark.py` 断言（arkcli 路径与 openapi 共用映射，fixture 中 `session` period 解析为 5 小时窗口、`window_label` 显示「5 小时」）；验证 `python -m pytest tests/test_provider_ark.py -q` 通过

## 3. 卡片单行布局与段宽配置

- [x] 3.1 `app/ui/card.py`：`_build_window_row` 改单行 HBox（`[类型名][进度条 stretch min32][百分比][已用/总量][重置时间]`），段宽读 config `row_layout`（name/percent/usage/reset），卡宽读 `card_width`（默认 380）；`MONTHLY_FREEZE` 行保持「名称+徽章」并沿用 `name_width`；`app/config.py` 增加带中文注释的默认值；验证 `tests/test_ui_card.py` 更新（单行包含五段、段宽应用、卡宽应用）
- [x] 3.2 缺失字段占位对齐：无重置时间/无用量时对应段显示空占位不破坏对齐、不显示 0；验证单测覆盖「仅百分比」（ark Coding Plan 形态）与「字段齐全」两种快照

## 4. 窗口行隐藏与恢复

- [x] 4.1 `app/ui/card.py` + `app/ui/window.py`：主窗口右键菜单按当前数据出现的窗口类型生成「隐藏5 小时 / 隐藏本周 / 隐藏本月」可勾选开关（交互同「始终置顶」）；勾选全局隐藏所有卡片该类型行，`hidden_window_types` 持久化到 `state.json`，取消勾选恢复；卡片渲染按类型过滤；验证单测：勾选后两张卡片的本月行均消失、重启（重新构造）后仍隐藏、取消勾选恢复、菜单仅含当前出现的窗口类型

## 5. 刷新无闪烁（原地更新）

- [x] 5.1 `app/ui/card.py`：`AccountCard` 拆「骨架 + `update_snapshot()`」两段，行级按窗口类型 diff，状态在 error/ok/stale 间切换时全量重建行集合；验证单测：同一快照两次 `update_snapshot` 复用全部行控件、窗口集合增减时行增删
- [x] 5.2 `app/ui/window.py`：`render_snapshots` 按 `vendor|account|plan` diff——已存在卡 `update_snapshot`、新卡插入、消失卡才移除；`_lock_size_to_content` 加尺寸变化守卫；渲染过程 `setUpdatesEnabled(False/True)` 包裹；验证单测：两次渲染同数据时卡片对象为同一实例、卡片增删时其余卡不重建；手动验证刷新无整窗闪烁

## 6. 系统托盘

- [x] 6.1 新增 `app/ui/tray.py`：`TrayController`——QPainter 绘制圆点图标、按全部可见卡片最紧窗口剩余比例分级着色（复用 warn/danger 阈值，冻结计 0，无数据灰色）、tooltip 逐卡摘要（超 6 行截断）、左键切换悬浮窗显隐、右键菜单（显示/隐藏悬浮窗、立即刷新、退出）、`isSystemTrayAvailable()` 为 False 时跳过并打中文日志；`app/main.py` 完成接线；验证单测（离屏）：状态色分级纯函数、tooltip 文本与截断、菜单项存在、托盘不可用时不抛异常

## 7. 文档与集成验证

- [x] 7.1 更新 `config.example.jsonc`（列表格式 + `visible` + `row_layout` + `card_width` + 迁移说明）与 `README.md`（配置章节改列表格式并附旧→新迁移示例、单行布局与段宽说明、行隐藏说明、托盘说明、QA 清单补项）；验证：示例文件可被 `parse_jsonc` 解析、README 示例与新 schema 一致
- [x] 7.2 集成验证：`python -m pytest` 全量通过；按 README QA 清单手动验证——仅列已购厂商出卡、单行布局与段宽配置生效、右键隐藏/恢复本月行并重启保持、刷新无闪烁、托盘图标变色/悬停摘要/左键显隐、旧 dict 配置显示迁移提示

## Workflow follow-up

- 实施完成并 review 后运行 `/opsx-archive` 归档本变更。
- 归档后确认 `openspec/specs/quota-widget` 与 `openspec/specs/quota-providers` 主规格已合并增量。
