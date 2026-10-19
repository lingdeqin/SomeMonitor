# Design

## Context

应用为 PySide6 桌面悬浮窗（`python -m app.main`），默认配置/状态路径锚定源码仓库根（`Path(__file__).parent.parent`）；重置时间当前显示绝对本地时间；无自启机制。Windows 用户路径：打包成 exe 分发。

## Goals / Non-Goals

**Goals:**

- PyInstaller 打包可用且实测通过（onefile / windowed），exe 首次运行在自身目录生成 `config.jsonc`
- 右键菜单「开机自启」开关，读写 HKCU Run 键
- 重置段显示相对倒计时（明确分级格式）

**Non-Goals:**

- 不做安装器（setup/MSI）、快捷方式、图标资源文件
- 不做开机自启的「最小化启动」「延迟启动」等策略
- 不改变刷新调度（倒计时精度随刷新周期，默认 60s ±1 分钟）

## Decisions

### D1 打包：PyInstaller onefile + windowed + run.py 入口

- 新增根目录 `run.py`（`from app.main import main`），规避 `python -m app.main` 的包语义对入口脚本化的影响；源码用法不变。
- `app/config.py` 增加冻结感知：`sys.frozen` 时默认 `config.jsonc` / `state.json` 锚定 `sys.executable` 所在目录（onefile 下即 exe 旁边），否则维持仓库根行为。
- windowed 模式下 `sys.stdout` 可能为 `None`：两处诊断 `print`（未知 vendor、托盘不可用）加 `sys.stdout` 守卫，行为不变。
- 构建命令（README 详述）：`python -m PyInstaller --noconfirm --onefile --windowed --name SomeMonitor --hidden-import httpx run.py`；`--hidden-import httpx` 是 ark 直连通道函数内延迟导入的保险；arkcli 子进程通道不在包内（运行期依赖本机 arkcli，README 说明）。
- `.gitignore` 增加 `build/`、`dist/`。

### D2 开机自启：注册表 Run 键为唯一事实源

- 新增 `app/autostart.py`：`autostart_command()` / `is_autostart_enabled()` / `set_autostart_enabled(bool)`，键名 `SomeMonitor`，读写 `HKCU\...\Run`（winreg）。
- 启动命令：frozen → `"<exe>"`；源码 → 优先 `pythonw.exe`（避免登录时弹控制台）执行绝对路径 `run.py`，均不依赖工作目录。
- 菜单开关不落 state.json——注册表即持久化与真值，避免双源漂移；建菜单时查询注册表设置勾选态。
- 注册表操作异常（权限/键缺失）捕获 `OSError`：查询返回 False，写入失败静默（下次菜单如实显示未生效）。

### D3 重置倒计时：纯函数格式化 + 渲染期取 now

- `card.py` 模块级 `format_reset_countdown(reset_at, now)`：距重置不足 1 分钟（含已到期）→ 「即将重置」；`days >= 1` → 「D天H小时后重置」；`1h <= delta < 1d` → 「H小时M分后重置」；`< 1h` → 「M分后重置」；`reset_at is None` → 空串占位。分钟向下取整。
- `WindowRow.update_window` 以 `datetime.now(timezone.utc)` 调用（`reset_at` 恒为 aware，见 `parse_datetime`）；文本只在刷新渲染时更新，陈旧度 ≤ 一个刷新周期。
- 备选「绝对+倒计时双显示」被否：单行段宽有限，用户明确要倒计时。

## Risks / Trade-offs

- [onefile 首次启动解压耗时（数秒）] → README 提供 onedir 备选命令（启动更快）。
- [windowed exe 下 arkcli 子进程（npm .cmd 垫片）每轮刷新闪终端] → `subprocess.run` 加 `CREATE_NO_WINDOW`（回归单测锁定）。
- [倒计时随刷新周期陈旧 ±1 分钟] → 可接受；不改刷新调度。
- [源码形态自启命令依赖 run.py 与解释器路径不变] → 迁移 Python 后需重勾选一次；注册表命令以绝对路径生成，重勾即修正。
- [windowed 下诊断输出不可见] → 仅两处提示性 print，功能不受影响。

## Migration Plan

- 无配置格式变化；`run.py`、`app/autostart.py` 均为新增，回滚即删。
- 打包产物不入库（gitignore）；源码运行路径行为不变（`default_config_path` 仅在 frozen 分支改变）。
