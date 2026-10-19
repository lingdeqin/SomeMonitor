# Proposal

## Why

用户需要把悬浮窗分发给日常使用（打包为独立 exe）、随开机常驻（开机自启），并希望重置时间直接可读（相对倒计时比绝对时间戳更直观）。

## What Changes

- **打包**：提供 PyInstaller 打包路径——`run.py` 启动入口、冻结感知的默认配置路径（exe 同目录的 `config.jsonc` / `state.json`）、windowed 模式下 print 安全守卫、README 打包章节；不改变源码运行方式（`python -m app.main` 依旧可用）。
- **开机自启**：右键菜单新增「开机自启」可勾选开关（交互同「始终置顶」），读写 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` 注册表键；打包后注册 exe 路径，源码运行注册 `pythonw run.py` 命令。
- **重置倒计时**：窗口行重置时间由绝对时间（`重置 10-31 00:00`）改为相对倒计时——小于 1 天显示「xx小时xx分后重置」（不足 1 小时显示「xx分后重置」），大于等于 1 天显示「xx天xx小时后重置」；已过期显示「即将重置」。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `quota-widget`:
  - 新增 Requirement：开机自启（注册表 Run 键开关、菜单可勾选、重启后状态一致）
  - 卡片式额度展示：重置时间改为相对倒计时显示（修改既有 Requirement，含格式规则）

## Impact

- 代码：`run.py`（新增入口）、`app/config.py`（frozen 感知默认路径）、`app/autostart.py`（新增，winreg 读写）、`app/ui/window.py`（菜单项）、`app/ui/card.py`（倒计时格式化）、`app/providers/__init__.py` 与 `app/ui/tray.py`（print 守卫）。
- 构建：引入 PyInstaller（开发机工具，非运行时依赖）；`.gitignore` 增加 `build/`、`dist/`。
- 文档：README 增加打包、开机自启、倒计时说明与 QA 项。
- 测试：`tests/test_autostart.py`（新增）、`tests/test_ui_card.py`（倒计时用例）、`tests/test_config.py`（路径行为）。
