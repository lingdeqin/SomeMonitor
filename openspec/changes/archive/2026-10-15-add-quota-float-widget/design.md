# Design

## Context

本项目为 greenfield（除 OpenSpec 规划产物外无任何代码）。前期探索已实证四家厂商的额度查询途径与各自已知的解析坑（见 D6 端点契约表）；本机已具备 arkcli（已登录）与 opencode CLI 登录态，为「零配置优先」提供了现实条件。动机见 proposal.md - Why，行为要求见 specs/quota-providers 与 specs/quota-widget。

## Goals / Non-Goals

**Goals:**
- 零配置优先：能从本机 CLI 登录态拿到凭证的厂商，装好即用
- 厂商间完全隔离：单家失败或未配置不影响其他家
- 可扩展：新增一家厂商 = 新增一个 Provider 模块，框架与 UI 零改动
- 轻量常驻：低资源占用的个人桌面工具

**Non-Goals:**
- 不做 Kimi 月度会员的**自动 Cookie 获取**（用户需手动从浏览器复制 `kimi-auth`；配置后走非官方 GetSubscriptionStats 显示月度共享额度，接口失败静默省略月度窗口）
- 不做任何写操作（购买/续费/轮换 Key）
- 不做账单金额、token 消耗时序、按模型拆分明细
- 不做 macOS/Linux 打包、托盘常驻、开机自启、推送告警
- v1 不做密钥加密存储（记录为后续 Windows DPAPI 演进项）

## Decisions

### D1 技术栈：Python 3.9+ + PySide6
本机实测 Python 3.9.7（代码全部 3.9 兼容，未用 3.10+ 语法）。备选：Tauri 2（体积更小、社区有同类悬浮窗先例，但 Rust 工具链重、编译迭代慢）、Electron（内存占用过大，个人小工具不值）。PySide6 原生提供 frameless / always-on-top / translucent / `setWindowOpacity` 与 QTimer；`subprocess` + httpx 覆盖全部采集需求；无编译步骤，适合个人工具快速迭代。

### D2 模块划分
```
app/
  main.py            # 入口: QApplication + 装配
  model.py           # 归一化数据模型与推导 helper
  config.py          # config.jsonc（JSONC 用户配置，App 只读）+ state.json（运行时状态）加载/保存
  providers/
    base.py          # BaseProvider + 凭证三级解析 + 注册表
    opencode_go.py   # OpenCode Go
    ark.py           # 火山方舟（双通道）
    glm.py           # 智谱 GLM（cn / z.ai）
    kimi.py          # Kimi for Coding
  service.py         # QuotaService：轮询调度 / last-good / stale 标注（纯逻辑）
  ui/
    window.py        # 主窗体: 无边框/置顶/拖拽/右键菜单
    card.py          # 厂商卡片渲染
  tests/             # pytest + 各家离线 fixture
```

### D3 归一化数据模型
`QuotaSnapshot { vendor, account_label, plan_label, status, windows[] }`；`QuotaWindow { type: 5h|weekly|monthly|session, used?, total?, percent?, reset_at? }`——字段可选语义：端上缺就缺，不伪造。推导规则集中在 model.py：字符串数字解析、`used = total - remaining` 推导、`percent = used/total` 兜底。

### D4 凭证三级解析链
每 Provider 声明 `credential_chain: [config_key, env_names, cli_discovery]`，base 统一逐级解析、命中即止。CLI 发现点：
- opencode → `~/.config/opencode/auth.json`
- kimi-code → `%USERPROFILE%\.kimi-code\credentials\*.json`（兼容旧 `~/.kimi/credentials/kimi-code.json`）
- ark → arkcli 子进程通道本身即发现（其自带 SSO 登录态）

### D5 火山方舟多通道
- 账号带 `profile` → 子进程 `arkcli --profile <名> usage plan --format json`（控制面多账号的正规机制；`--api-key` 仅数据面、控制面命令不消费）
- `transport=auto`：IAM AK/SK 成对 → SigV4 直连 `ark.cn-beijing.volcengineapi.com`（HMAC-SHA256，region=cn-beijing，service=ark，version=2024-01-01，动作 `GetCodingPlanUsage` / `GetAFPUsage`）；只有 `ark-` API Key 无 SK → 明确报错并指引 profile（实测直连 400）；否则 → 默认 arkcli 子进程
- arkcli 输出 schema：顶层 `viewer` + `items[].periods[]`（官方文档）

### D6 各厂商端点契约与已知坑（已按 2026-10-14 实测校准，证据 `.omo/evidence/`）
| 厂商 | 端点 | 鉴权 | 已知坑 |
|---|---|---|---|
| OpenCode Go | `GET https://opencode.ai/zen/go/v1/usage` | Bearer Key 或 opencode auth.json 自动发现 | 实测形状：`usage.rolling/weekly/monthly` 各含 `percent`(0-100) 与 `resetsAt`（驼峰、3 位小数秒）；无 used/total |
| 智谱 GLM | `GET {base}/api/monitor/usage/quota/limit`（base：`open.bigmodel.cn` 国内 / `api.z.ai` 国际） | `Authorization: <裸Key>`（实测可用；401 自动换 Bearer 回退） | 实测字段：`type=CREDIT_LIMIT`，`unit=3`→5h、`unit=6`→周；`usage`=总量、`currentValue`=已用、`remaining`、`percentage`(0-100)、`nextResetTime`=epoch 毫秒；`data.level`=档位 |
| Kimi | `GET https://api.kimi.com/coding/v1/usages`；月度另走 `POST https://www.kimi.com/apiv2/...MembershipService/GetSubscriptionStats` | Bearer `sk-kimi-*`；月度用 `kimi_auth` Cookie（账号配置或 `KIMI_AUTH_TOKEN`） | 数值是字符串；`resetTime` PascalCase；`used` 常缺省→`limit-remaining` 推导；`totalQuota` 是月度冻结二元信号（`used>0` 即冻结），不是百分比；月度 `amount_used_ratio` 为 0-1 比率，失败静默省略月度窗口 |
| 火山方舟 | arkcli 子进程（含 `--profile`）/ IAM AK+SK SigV4 直连 `ark.cn-beijing.volcengineapi.com` | SSO 登录态 / AK+SK | 控制面真实主机为 `ark.cn-beijing.volcengineapi.com`（非 `open.volcengineapi.com`）；`ark-` API Key 直连控制面实测 400（只认 SSO / IAM SigV4），多账号须用 arkcli profile；CodingPlan `percent` 为 0-1 比率（解析归一化）；`updated_at` 实测为秒级 epoch |

### D7 悬浮窗 UI 关键实现
`Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool` + `WA_TranslucentBackground`（圆角卡片观感）+ `setWindowOpacity(0.3–1.0，默认 0.9)`（右键菜单滑块调节，即时生效并写回 config）。拖拽：mousePress/mouseMove 全局坐标差。位置与大小持久化到 config.json。

### D8 刷新与降级
QTimer（`refresh_seconds`，默认 60s）+ 手动刷新；每轮并发调用全部启用 Provider；Provider 级 last-good 快照 + `fetched_at` 时间戳；失败 → 卡片标注「获取失败 HH:MM，显示旧数据」，恢复自动清除。

### D9 配置与安全
用户配置独立为 `config.jsonc`（JSONC：支持 `//` 注释与尾随逗号，字符串感知的单趟扫描解析；首启生成带中文注释的模板，此后 **App 只读、绝不覆盖**——用户注释安全）。运行时状态（窗口位置、菜单调整的不透明度/置顶）由 App 读写 `state.json`；取值优先级：`state.json` > `config.jsonc` > 内置默认。密钥明文存于 config.jsonc（已 `.gitignore`）：README 明示风险与环境变量注入替代；日志与错误信息绝不输出密钥明文。

### D10 测试策略
各家 Provider 用离线 fixture JSON 单测（覆盖 D6 表中全部坑）；模型推导规则全单测；UI 按手动 QA 清单验证（启动/拖拽/菜单/不透明度/降级态）。GUI 不做自动化端到端。

## Risks / Trade-offs

- [OpenCode Go / 智谱 monitor 接口为社区实证、无官方文档，可能变更] → Provider 隔离使影响限于单家；fixture 使解析失败快速定位；错误态明确提示
- [GLM 鉴权头格式分歧] → 首选格式 401 时自动回退另一种，两种格式均有 fixture 覆盖
- [密钥明文存储] → v1 接受（个人本机工具），文档给出环境变量注入替代，后续可演进 DPAPI 加密
- [arkcli 登录态过期] → 错误态提示运行 `arkcli auth login`，不自动触发登录流程
- [PySide6 内存占用（约 60–100MB）] → 个人桌面工具可接受；Tauri 备选已记录在案
- [Kimi `totalQuota` 语义误读（当作百分比绘制）] → 按「月度冻结二元信号」实现，卡片以冻结/正常呈现，fixture 覆盖冻结与正常两种状态

## Migration Plan

greenfield，无存量迁移。回滚 = 删除 `app/` 目录与 `config.json`。

## Open Questions

（无——阻塞决策已在探索阶段解决；实现期待验证项均已在 D6 记录，且任务清单中配有对应 fixture 步骤。）
