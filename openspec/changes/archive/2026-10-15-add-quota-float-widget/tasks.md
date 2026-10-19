# Tasks

## 1. 项目骨架与配置

- [x] 1.1 创建 `app/` 目录结构与 `requirements.txt`（PySide6、httpx、pytest），建立 `main.py` 入口骨架；验证：`pip install -r requirements.txt` 成功，且 `python -m pytest` 在空测试集下退出码为 0
- [x] 1.2 实现 `app/config.py`（加载/生成默认 `config.json`：`refresh_seconds=60`、`opacity=0.9`、`always_on_top=true`、各厂商账号数组、ark `transport=auto`）并编写 `tests/test_config.py`（默认值生成、字段覆盖、文件缺失回退）；验证：`python -m pytest tests/test_config.py` 通过

## 2. 归一化模型与 Provider 框架

- [x] 2.1 实现 `app/model.py`（QuotaSnapshot / QuotaWindow / 状态枚举 + 字符串数字解析、`used = total - remaining` 推导、percent 兜底计算）并编写 `tests/test_model.py`，覆盖 quota-providers spec「统一额度数据模型」的四个场景（字段齐全 / 仅百分比 / 字符串数字 / 已用推导）；验证：`python -m pytest tests/test_model.py` 通过
- [x] 2.2 实现 `app/providers/base.py`（BaseProvider：凭证三级解析链、并发采集入口、错误隔离包装、Provider 注册表）并编写 `tests/test_base.py`（fake Provider 验证解析优先级：显式配置 > 环境变量 > CLI 登录态，三级未命中 → 「未配置」态）；验证：`python -m pytest tests/test_base.py` 通过

## 3. 四家 Provider 实现（每家含离线 fixture 单测）

- [x] 3.1 实现 `app/providers/opencode_go.py`：`GET https://opencode.ai/zen/go/v1/usage`（Bearer Key 或 opencode auth.json 自动发现）；先用真实 Key 抓一次响应样本落为 fixture 并钉死字段映射；验证：`python -m pytest tests/test_provider_opencode_go.py` 通过（真实样本抓取依赖用户 API Key，见 Workflow follow-up）
- [x] 3.2 实现 `app/providers/glm.py`：`{open.bigmodel.cn|api.z.ai}/api/monitor/usage/quota/limit`，`Authorization` 头双格式自适应（首选格式 401 自动换另一种），解析 `data.limits[]`（unit=3→5h、unit=6→周、TIME_LIMIT→月）与 `data.level`；验证：`python -m pytest tests/test_provider_glm.py` 通过（fixture 覆盖两种鉴权格式与三窗口）
- [x] 3.3 实现 `app/providers/kimi.py`：`GET https://api.kimi.com/coding/v1/usages`（Bearer `sk-kimi-*`），解析字符串数值 / `resetTime` / used 缺省推导 / `totalQuota` 月度冻结二元信号；验证：`python -m pytest tests/test_provider_kimi.py` 通过（fixture 覆盖正常、used 缺省、月度冻结三态）
- [x] 3.4 实现 `app/providers/ark.py`：`transport=auto`（配置 AK/SK → SigV4 直连 `GetCodingPlanUsage` / `GetAFPUsage`，region=cn-beijing、service=ark、version=2024-01-01；否则 arkcli 子进程 `arkcli usage plan --format json`），arkcli 未登录 → 错误态给出登录指引；验证：`python -m pytest tests/test_provider_ark.py` 通过（arkcli 输出 fixture 解析 + SigV4 签名构造单测；真机实跑出数，CodingPlan percent 实测为 0–1 比率已归一化，证据 `.omo/evidence/ark_live.json`）

## 4. 悬浮窗 UI（中文）

- [x] 4.1 实现 `app/ui/window.py` 主窗体：无边框 / 置顶 / `WA_TranslucentBackground` / 鼠标拖拽 / 位置持久化；验证：启动悬浮窗可拖动，重启后位置保留（手动 QA 清单项；离屏单测已覆盖拖拽与持久化逻辑，GUI 真机启动 12s 存活验证通过）
- [x] 4.2 实现 `app/ui/card.py` 卡片渲染：每账号一卡、多窗口进度条 + 百分比 + 本地时区重置时间、分级警示色（默认剩余 ≤30% 黄 / ≤10% 红，阈值可配）、Kimi `totalQuota` 以「月度冻结/正常」呈现而非进度条；验证：注入 fake 快照渲染四家卡片并截图核对（手动 QA 清单项；离屏渲染单测含截图落盘）
- [x] 4.3 实现右键菜单：立即刷新 / 不透明度滑块（0.3–1.0 即时生效并写回配置）/ 置顶开关 / 退出，全中文文案；验证：手动 QA 清单项（调节即时生效、重启保留；离屏单测已覆盖菜单结构与持久化）

## 5. 调度、集成与文档

- [x] 5.1 实现轮询调度：QTimer（`refresh_seconds`）+ 手动刷新 + Provider 级 last-good 与 stale 标注（「获取失败 HH:MM，显示旧数据」，恢复自动清除）；验证：fake Provider 的状态转换单测通过（成功 → 失败 → 恢复）
- [x] 5.2 端到端装配 `app/main.py`：启动即并发采集全部启用厂商并渲染；验证：本机真实运行——arkcli 已登录时火山方舟卡片出数（实测 Coding Plan 91.56%/12.21%/6.10% 三窗口），未配置厂商显示「未配置」，GUI 存活 12s 无异常
- [x] 5.3 编写中文 `README.md`：安装步骤、`config.json` 各字段说明、四家凭证获取途径（kimi.com/code/console、`arkcli auth login`、opencode auth.json、GLM API Key）、密钥明文风险与环境变量替代、已知限制；验证：按 README 从零执行能启动应用

## 6. 集成检查

- [x] 6.1 全量单测通过（`python -m pytest`）且手动 QA 清单全部勾选；验证：输出测试摘要与勾选后的 QA 清单（111/111 单测通过；手动 QA 清单经用户真实使用核验后确认归档）

## 7. 配置文件拆分（用户后续要求：用户配置单独一个 jsonc 文件）

- [x] 7.1 用户配置改为独立的 `config.jsonc`（JSONC：支持 `//` 注释与尾随逗号，字符串感知单趟解析——`"https://..."` 与字符串内 `", }"` 不受影响；首启生成中文注释模板，此后 App 只读不写）；运行时状态拆到 `state.json`（窗口位置/菜单调整的透明度/置顶；取值优先级 state > config.jsonc > 内置默认）；验证：`python -m pytest` 84 项全通过；真机冒烟确认模板自动生成（UTF-8 中文注释完好）、GUI 启动存活 10s、`state.json` 仅在关窗/调节时写入

## 8. 退出与刷新缺陷修复（用户反馈：Ctrl+C 与菜单退出均无效）

- [x] 8.1 修复退出：Qt.Tool 窗口不参与 last-window-closed 判定 → 菜单「退出」与 closeEvent 统一调用 `QApplication.quit()`（任何关闭方式都结束事件循环）；Ctrl+C 安装 SIGINT 处理器 + 300ms 信号泵定时器；验证：真机 taskkill（WM_CLOSE）优雅退出、state.json 落盘、stderr 无 Traceback
- [x] 8.2 修复 RefreshWorker 生命周期：移除 deleteLater（曾致 C++ 对象先于引用销毁，每轮刷新抛 RuntimeError、数据停更），改由 `self._worker` 引用保活、下轮替换回收；closeEvent 等待运行中线程（≤3s）；验证：回归单测（连续 refresh / 运行中跳过 / quit 路径）
- [x] 8.3 渲染尺寸稳定：布局 activate 后 `setFixedSize(总最小尺寸)` + 事件循环空闲后二次锁定终态；验证：单测断言 size == totalMinimumSize（setGeometry 告警为 Qt 平台层噪音，已在 README 记录为无害）

## 9. 数据获取修复与优化（用户反馈：opencode/glm 无数据、ark 多账号同数据、kimi 无月度、小数位）

- [x] 9.1 OpenCode Go 解析按 2026-10-14 实测响应校准（`usage.rolling/weekly/monthly` + `percent`(0-100) + `resetsAt` 驼峰键），fixture 同步替换为实测形状；验证：真机实跑出数（rolling 0% / weekly 80% / monthly 40%）+ 单测
- [x] 9.2 智谱 GLM 解析按实测校准（`type=CREDIT_LIMIT`、`unit=3/6`、`usage`=总量、`currentValue`=已用、`percentage`、`nextResetTime`=epoch 毫秒）；裸 Key 鉴权实测有效；验证：真机实跑出数（LITE 档位，5h 0/2000，weekly 69%）+ 单测
- [x] 9.3 火山方舟多账号：账号级 `profile` 支持（`arkcli --profile`，控制面正规机制）；`ark-` API Key 无 SK 从「静默回落本机会话（多账号显示同一份数据）」改为明确报错指引 profile；SigV4 直连主机修正为 `ark.cn-beijing.volcengineapi.com`（arkcli --debug 实测发现）；验证：单测（命令构造 / profile 路由 / 报错指引）+ 真机双账号按预期给出指引
- [x] 9.4 Kimi 月度会员共享额度（可选）：账号 `kimi_auth` 或 `KIMI_AUTH_TOKEN` Cookie 走 GetSubscriptionStats 非官方接口，`amount_used_ratio` 0-1 比率归一化，失败静默省略月度窗口；验证：解析单测（比率归一化 / 驼峰 / >1 透传 / 无效返回 None）
- [x] 9.5 显示优化：百分比与数值最多保留两位小数（91.5607→91.56、6.10→6.1、100.0→100）；验证：渲染单测

## 10. 第二轮用户反馈（profile 同数据 / 进度条一致性 / kimi_auth 说明 / 配置示例）

- [x] 10.1 火山方舟「两个 profile 数据相同」定因：实测取证发现两个 profile 同属一个火山账号（account_id 均 2132935106、同一把默认 Key）——一次 SSO 登录会为同账号派生多类型 profile；新增 UI 自诊断（多账号解析到同一 viewer account_id 时卡片标注「与其他账号为同一火山账号」），README/示例/报错指引同步改写（多账号推荐 IAM AK/SK 直连）；验证：解析携带 viewer_account_id + 重复标注单测（含同账号多计划不误报）
- [x] 10.2 进度条等长：窗口行改两行布局（首行 [类型名][进度条][百分比] 首尾固定宽度，用量/重置时间移至第二行），有无重置时间不再影响进度条长度；验证：单测断言两行进度条宽度相等（含 GLM 无重置场景）
- [x] 10.3 kimi-auth Cookie 获取说明：README 新增逐步说明（F12 → 应用 → Cookie → kimi.com → kimi-auth 字段，含控制台 document.cookie 偷懒法与过期说明）
- [x] 10.4 新增 `config.example.jsonc`：覆盖全部可配置项（含 ark 三种账号写法、GLM 双通道、kimi_auth）逐项中文注释，可入库作文档
- 验证：`python -m pytest` 102 项全绿

## 11. Kimi 月度失败可视化（用户反馈：复制了 cookie 仍无月度）

- [x] 11.1 定因：实测（5 种请求变体探测 GetSubscriptionStats）确认请求格式正确（POST + JSON，路由存在），用户 cookie 的 JWT `exp`=2026-08-19 **已过期约两个月**，服务端返 `REASON_INVALID_AUTH_TOKEN / Session expired`
- [x] 11.2 失败可视化：月度获取失败不再静默跳过——卡片底部显示灰字提示行「月度会员额度获取失败：Cookie 可能已过期（本地解码有效期至 XXXX-XX-XX），请重新复制 kimi-auth」；QuotaSnapshot 新增 notes 通用提示字段并接入卡片渲染；验证：单测（JWT exp 本地解码 / 失败加注 / 成功无注 / 卡片渲染），`python -m pytest` 106 项全绿

## 12. Kimi 网页端凭证迁移（用户反馈：新浏览器已无 kimi-auth Cookie，接口改带 authorization 头）

- [x] 12.1 月度会员接口鉴权方式从 Cookie 迁移到 `Authorization` 请求头（用户在浏览器 Network 面板实证 Kimi 改版）；`kimi_auth` 字段兼容裸 JWT 与完整 `Bearer xxx` 两种粘贴形式；失败提示文案同步更新（指引复制 authorization 最新值）；README 获取步骤与 config.example.jsonc 说明重写；验证：`python -m pytest` 107 项全绿（含双形式请求头单测）；待用户填入新凭证后实测校准响应解析

## 13. Kimi 月度凭证自动续期（用户配合逆向：refresh_token + RefreshToken 接口）

- [x] 13.1 用户实证 Kimi 网页端已迁移：localStorage 持有 access_token（实测 15 分钟寿命）+ refresh_token（90 天）；续期接口 `POST auth.kimi.com/api/account.gateway.v1.AuthService/RefreshToken`（body `{refresh_token}`，响应 `{accessToken, refreshToken}`）
- [x] 13.2 旋转语义实测：**软旋转**（旧 refresh_token 换新后仍 200 可用）——浏览器与悬浮窗可共用同一条凭证链互不失效，无需持久化旋转后的新 token
- [x] 13.3 实现自动续期链路 refresh_token → RefreshToken → accessToken → GetSubscriptionStats；access token 内存缓存（过期前 2 分钟内不重复换）；失败提示区分 refresh_token / 手动 kimi_auth 两种来源；README 与 config.example.jsonc 改为推荐 refresh_token 方式
- 验证：`python -m pytest` 111 项全绿（缓存/回退/失败提示单测）；真机 E2E 月度窗口出数（monthly 0.84%，含重置时间）

## Workflow follow-up

- 实现与集成检查完成后，由用户复核 spec 与实现的一致性，再执行归档流程（`/opsx-archive`）
- 归档后用 `openspec list --specs` 确认 `quota-providers` 与 `quota-widget` 已进入主 spec 清单
- （已完成 2026-10-14）OpenCode Go / GLM 真实响应校准：用户配置 Key 后实测抓样，解析与 fixture 已按真实形状重写（证据 `.omo/evidence/opencode_go_live.json`、`glm_live_bare.json`）
- 用户侧待办：火山方舟多账号需按 README「火山方舟多账号」一节设置 arkcli profile 并把 config.jsonc 中的 `access_key_id` 改为 `profile` 引用；Kimi 月度额度需配置 `kimi_auth` Cookie
