# Tasks

## 1. 重置倒计时

- [x] 1.1 `app/ui/card.py`：新增模块级 `format_reset_countdown(reset_at, now)`（<1h「M分后重置」、<1d「H小时M分后重置」、>=1d「D天H小时后重置」、过期「即将重置」、None 空串），`WindowRow.update_window` 改用它并传 `datetime.now(timezone.utc)`；验证 `tests/test_ui_card.py` 新增四档格式 + 边界（恰好 1 天、恰好 1 小时）用例且全绿

## 2. 开机自启

- [x] 2.1 新增 `app/autostart.py`：`autostart_command()`（frozen→exe 路径；源码→pythonw 优先执行绝对 run.py）、`is_autostart_enabled()` / `set_autostart_enabled(bool)` 读写 `HKCU Run` 键（键名 SomeMonitor，OSError 容错）；验证 `tests/test_autostart.py` 用假 winreg（内存 dict）覆盖命令构造、开/关/查询往返、键缺失返回 False、删除不存在值不抛
- [x] 2.2 `app/ui/window.py`：右键菜单在「始终置顶」后新增「开机自启」可勾选开关，勾选态取 `is_autostart_enabled()`，切换调用 `set_autostart_enabled`；验证单测（monkeypatch autostart 函数）：菜单项存在、勾选态反映注册表、切换调用写函数

## 3. 打包

- [x] 3.1 新增根目录 `run.py` 入口；`app/config.py` 默认 config/state 路径 frozen 感知（exe 目录）；`app/providers/__init__.py` 与 `app/ui/tray.py` 的 print 加 `sys.stdout` 守卫；验证 `python run.py --help` 正常、`python -m pytest tests/test_config.py -q` 全绿、既有 `default_paths` 用例不回归
- [x] 3.2 安装 PyInstaller 并构建：`python -m PyInstaller --noconfirm --onefile --windowed --name SomeMonitor --hidden-import httpx run.py`；验证构建退出码 0、`dist\SomeMonitor.exe` 存在、从异 cwd 启动 exe（--config 指向临时目录）进程存活 ≥8s 且模板 config.jsonc 生成、结束后清理测试产物
- [x] 3.3 修复 windowed exe 周期性闪终端：`ark.py` arkcli 子进程加 `CREATE_NO_WINDOW`（windowed 无控制台进程 spawn npm .cmd 垫片必闪终端，周期=刷新间隔）；验证回归单测断言 `creationflags` 传入、全量 pytest 通过、exe 重建

## 4. 文档与集成验证

- [x] 4.1 README：新增「打包发布」章节（onefile/onedir 命令、产物路径、exe 旁 config.jsonc、arkcli 运行期依赖说明）、「开机自启」与「重置倒计时」说明、QA 清单补项；验证示例命令与实际构建命令一致
- [x] 4.2 集成验证：`python -m pytest` 全量通过；`openspec validate add-autostart-and-countdown` 通过；QA 临时资源（临时 config/exe 测试目录）清理完毕
