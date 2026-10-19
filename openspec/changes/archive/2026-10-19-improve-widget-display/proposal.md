# Proposal

## Why

悬浮窗当前按厂商字典固定展示四家卡片（未购买套餐的厂商也占位显示「未配置」）、额度窗口行两行排版占高且段宽不可调、每次刷新整窗销毁重建导致闪烁，且缺少托盘常驻入口。本变更按用户实测反馈一次性改进展示形态、配置灵活性与常驻体验。

## What Changes

- **BREAKING** `config.jsonc` 的 `providers` 从按厂商的字典改为**数组列表**：每项含 `vendor`（厂商）、`visible`（是否显示/实例化）及原有账号配置；旧字典格式不再支持，检测到旧格式时在界面给出明确迁移提示。
- 额度窗口行改**单行展示**：`[类型名][进度条][百分比][用量][重置时间]` 一行排完，各段宽度可在 config 中配置，卡片总宽可配置。
- 主窗口右键菜单提供**按窗口类型的隐藏开关**（与「始终置顶」一致的勾选式交互）：按当前数据出现的窗口类型动态生成「隐藏5 小时 / 隐藏本周 / 隐藏本月」等项，勾选后全局隐藏所有卡片该类型行并持久化到 `state.json`，取消勾选恢复。
- 火山方舟 Coding Plan 的「会话」窗口映射为「5 小时」显示（ark 的 `session` period 归一化为 `5h` 窗口类型）。
- 修复刷新闪烁：渲染从「全量销毁重建」改为**按 key 原地复用更新**，尺寸仅在变化时锁定。
- 新增 **Windows 系统托盘集成**：托盘图标按整体额度状态变色（绿/黄/红），悬停提示额度摘要，左键点击显示/隐藏悬浮窗，右键菜单含刷新/退出。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `quota-widget`:
  - 卡片式额度展示：窗口行改为单行布局，段宽可配置（新增/修改 Requirement）
  - 新增 Requirement：窗口类型隐藏开关（主菜单可勾选、按类型全局生效、持久化）
  - 新增 Requirement：刷新稳定性（原地更新，不整体消失重建）
  - 新增 Requirement：系统托盘集成（图标状态色、悬停摘要、显隐切换、菜单）
- `quota-providers`:
  - 新增 Requirement：Provider 列表式配置（`vendor` + `visible`，数组顺序决定卡片顺序，未列出或 `visible: false` 的厂商不实例化不显示；旧字典格式给出迁移提示）
  - 统一额度数据模型：火山方舟 `session` 窗口归一化为 `5h`（「5 小时」）

## Impact

- 代码：`app/config.py`（新配置 schema + 模板）、`app/providers/__init__.py`（按列表构建 Provider）、`app/providers/base.py`（provider_config 适配）、`app/providers/ark.py`（session→5h 映射）、`app/ui/card.py`（单行布局 + 行隐藏 + 右键菜单）、`app/ui/window.py`（原地更新渲染 + 托盘）、`app/main.py`（托盘接线）、`app/ui/tray.py`（新增模块）。
- 配置与文档：`config.example.jsonc`、`app/config.py` 内置模板、`README.md`（新配置格式、迁移说明、单行布局、隐藏行、托盘说明、QA 清单）全部更新。
- 兼容性：**破坏性**——旧 `providers` 字典配置不再生效；用户需按 README 迁移为列表格式。
- 测试：`tests/test_config.py`、`tests/test_provider_ark.py`、`tests/test_ui_card.py`、`tests/test_ui_window.py` 需同步调整并新增用例。
