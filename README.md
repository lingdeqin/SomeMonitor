# Coding Plan 额度悬浮窗

Windows 桌面常驻悬浮窗，一屏尽览多家 AI coding plan 的额度使用情况：

- **OpenCode Go**
- **火山方舟**（Coding Plan / Agent Plan，个人版 / 团队版）
- **智谱 GLM Coding Plan**（国内 bigmodel.cn / 国际 z.ai）
- **Kimi for Coding**

每个账号一张卡片，按额度窗口（5 小时 / 周 / 月）**单行**显示进度条、百分比、用量与重置时间；单家失败不影响其他家。配套**系统托盘图标**：颜色随整体额度状态变化，悬停看摘要，左键显隐悬浮窗。

## 安装与运行

要求：Python 3.9+，Windows。

```powershell
pip install -r requirements.txt
python -m app.main
```

可选参数：`python -m app.main --config D:\path\to\config.jsonc`（默认读取仓库根目录的 `config.jsonc`；不存在时自动生成带注释模板）。运行时状态写入同目录 `state.json`。

### 打包发布（PyInstaller）

```powershell
pip install pyinstaller
python -m PyInstaller --noconfirm --onefile --windowed --name SomeMonitor --hidden-import httpx run.py
```

- 产物：`dist\SomeMonitor.exe`（单文件、无控制台窗口）。首次启动需数秒解压；追求启动速度可去掉 `--onefile` 改为目录形态（`dist\SomeMonitor\`，启动明显更快）。
- **配置位置**：exe 首次运行在其**同目录**生成 `config.jsonc` 模板与 `state.json`（与源码运行的仓库根相互独立）。
- 火山方舟默认通道依赖本机 arkcli（npm 全局包 + 已登录），不在 exe 内；IAM AK/SK 直连通道无外部依赖。其余三家只走 HTTPS。arkcli 子进程已禁用控制台窗口（`CREATE_NO_WINDOW`），刷新时不会闪终端。
- 「开机自启」在打包形态下注册 exe 自身路径。

## 凭证配置（三级解析：显式配置 > 环境变量 > CLI 登录态）

能从本机 CLI 登录态拿到凭证的厂商**零配置**；其余按需配置。

| 厂商 | 凭证获取 | 环境变量 | CLI 自动发现 |
|---|---|---|---|
| OpenCode Go | opencode 账户 API Key | `OPENCODE_GO_API_KEY` / `OPENCODE_API_KEY` | `~\.config\opencode\auth.json` |
| 火山方舟 | 默认走本机 arkcli（先 `arkcli auth login`）；**多账号**：各账号分别登录后用 profile（见下）；或 IAM AK/SK 成对直连 | `ARK_ACCESS_KEY_ID` + `ARK_SECRET_ACCESS_KEY`（IAM 对） | arkcli 自带 SSO 登录态 |
| 智谱 GLM | 开放平台 API Key（国内 bigmodel.cn / 国际 z.ai） | `BIGMODEL_API_KEY`（国内）/ `ZAI_API_KEY`（国际） | 无 |
| Kimi | `kimi.com/code/console` 创建 `sk-kimi-*` Key（**不是** Moonshot 开放平台的 Key）；月度会员额度需另配 `refresh_token` | `KIMI_API_KEY` / `KIMI_CODING_API_KEY`；月度用 `KIMI_REFRESH_TOKEN` | `~\.kimi-code\credentials\*.json`（Kimi Code CLI 登录态） |

### 火山方舟多账号（重要，先读懂再配）

控制面额度查询跟**身份**走：`ark-` 开头的 API Key 不能直连控制面接口（实测 400）。且 arkcli 有两个容易踩坑的行为：

1. **一次 SSO 登录会为同一账号自动派生多个不同类型的 profile**（如 `coding-plan_cn-beijing_personal`、`platform_cn-beijing_accountwide`）——它们**不是多个账号**，数据完全相同。悬浮窗检测到这种情况会在卡片上标注「与其他账号为同一火山账号」。
2. **跨账号登录会切换本机激活身份**（可能重建 profile 集），一台机器同时保持多个账号的 arkcli 登录态并不可靠。

**真正的多账号做法（二选一）：**

- **IAM AK/SK 直连（推荐，确定可行）**：各账号在火山控制台创建 IAM 访问密钥，`config.jsonc` 中成对填写：
  ```jsonc
  { "label": "账号B", "access_key_id": "AKLTxxx", "secret_access_key": "xxx" }
  ```
- **arkcli profile 跨账号（不保证可用）**：浏览器登录账号 B → `arkcli auth login volc-sso` → `arkcli profile list --format json` 查看新 profile → 按名引用 `{ "label": "账号B", "profile": "<名>" }`。若登录后发现旧账号 profile 被清掉，说明你的 arkcli 版本一次只保留一个身份，请改用 IAM AK/SK。

不配 profile / AK/SK 的账号统一走本机默认 arkcli 登录态。

## config.jsonc 说明

用户配置独立存放在 `config.jsonc`（**支持 `//` 注释与尾随逗号**）。首次运行自动生成带中文注释的模板；之后 App 只读该文件、绝不改写——你的注释永远安全。已加入 `.gitignore`，不会入库。

窗口位置、右键菜单里调整的不透明度 / 置顶、被隐藏的窗口类型等**运行时状态**由 App 存到另一个文件 `state.json`，取值优先级：`state.json` > `config.jsonc` > 内置默认。

模板示例（节选）：

```jsonc
{
  // 自动刷新间隔（秒）
  "refresh_seconds": 60,
  // 整窗不透明度（0.3 - 1.0）
  "opacity": 0.9,
  // 剩余百分比告警阈值：<=30 黄色，<=10 红色
  "warn_percent": 30,
  "danger_percent": 10,
  // 卡片宽度（像素）
  "card_width": 380,
  // 窗口行各段宽度：类型名 / 百分比 / 已用总量 / 重置时间
  "row_layout": {
    "name_width": 52, "percent_width": 48,
    "usage_width": 88, "reset_width": 104
  },
  // 各厂商配置：数组顺序即卡片顺序；visible=false 或未列出 = 不采集不显示
  "providers": [
    { "vendor": "opencode-go", "visible": true, "accounts": [] },
    { "vendor": "ark", "visible": true, "transport": "auto", "accounts": [] },
    { "vendor": "glm", "visible": true, "accounts": [] },
    { "vendor": "kimi", "visible": true, "accounts": [] }
  ]
}
```

多账号 + 显式密钥 + GLM 国际版示例：

```jsonc
"providers": [
  { "vendor": "glm", "visible": true, "accounts": [
    { "label": "国内号", "api_key": "..." },
    { "label": "国际号", "api_key": "...", "channel": "global" }
  ]},
  { "vendor": "ark", "visible": true, "transport": "auto", "accounts": [
    { "label": "账号A", "profile": "<arkcli profile 名>" },
    { "label": "直连号", "access_key_id": "AK...", "secret_access_key": "SK..." }
  ]},
  { "vendor": "kimi", "visible": true, "accounts": [
    { "label": "主号", "api_key": "sk-kimi-...", "refresh_token": "eyJ..." }
  ]}
]
```

- `visible`：`false` 时该厂商不采集、不显示卡片（适合没购买套餐的厂商）；整项删除效果相同。
- `ark.transport`：`auto`（默认，IAM AK/SK 成对走直连否则 arkcli）/ `arkcli` / `openapi`。
- `kimi.refresh_token`：可选。配置后显示**月度会员共享额度**（走 kimi.com 网页端非官方接口，自动续期 access token，约 90 天有效；失败时自动省略月度窗口，不影响周限 / 5 小时）。获取步骤见下节；也可用环境变量 `KIMI_REFRESH_TOKEN`。

### 从旧版（按厂商字典）迁移

2026-10-16 起 `providers` 改为**数组**格式。旧版按厂商的字典配置不再支持——升级后悬浮窗会显示迁移提示。迁移方法：把 `providers: { "ark": {...}, "kimi": {...} }` 改写为：

```jsonc
// 旧（不再支持）                          // 新
"providers": {                            "providers": [
  "ark": { "accounts": [...] },       =>     { "vendor": "ark", "visible": true, "accounts": [...] },
  "kimi": { "accounts": [...] }       =>     { "vendor": "kimi", "visible": true, "accounts": [...] }
}                                        ]
```

没配的厂商直接不写（或 `"visible": false`），界面上就不会再出现「未配置」占位卡片。

## 显示定制

- **单行窗口行**：每个额度窗口一行显示 `[类型名][进度条][百分比][已用/总量][重置倒计时]`；`card_width` 与 `row_layout` 各段宽度可在 config 调整，进度条占据剩余空间。
- **重置倒计时**：重置段显示相对时间——不足 1 天为「xx小时xx分后重置」（不足 1 小时为「xx分后重置」，不足 1 分钟为「即将重置」），满 1 天为「xx天xx小时后重置」；随自动刷新更新（精度约一个刷新周期）。
- **开机自启**：右键菜单「开机自启」开关（交互同「始终置顶」）——写入/移除当前用户注册表 Run 键（`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`，键名 `SomeMonitor`）。打包后注册 exe 路径；源码运行注册 `pythonw run.py` 命令。
- **按类型隐藏窗口行**：主窗口右键菜单提供「隐藏5 小时 / 隐藏本周 / 隐藏本月」等**可勾选开关**（交互同「始终置顶」，仅列出当前数据中出现的窗口类型）；勾选后**所有卡片**隐藏该类型窗口行并存 `state.json`，取消勾选即恢复。
- **系统托盘**：通知区域常驻圆点图标——绿（正常）/ 黄（剩余 ≤ `warn_percent`）/ 红（剩余 ≤ `danger_percent`）/ 灰（无数据）；悬停显示各卡片最紧剩余摘要；**左键点击**显示/隐藏悬浮窗；右键菜单含显示隐藏、立即刷新、退出。托盘不可用时自动跳过，悬浮窗不受影响。

### Kimi 月度会员额度（refresh_token 自动续期，推荐）

Kimi 的月度会员共享额度不在官方 `/usages` 接口里，需要网页端凭证。网页端 access token 只有 **15 分钟**寿命，手动复制不现实；正确姿势是配置 **refresh_token**（约 **90 天**有效，悬浮窗自动续期 access token）：

1. 浏览器打开并登录 <https://www.kimi.com>；
2. `F12` → **「应用 / Application」** → 左侧**「本地存储 / Local Storage」→ `https://www.kimi.com`**；
3. 找到键名 **`refresh_token`** 那一行，复制**值**（`eyJ` 开头的长 JWT）；
4. 填进 `config.jsonc` 对应 Kimi 账号的 `"refresh_token"` 字段，保存即生效。

说明：

- **与浏览器互不干扰**：续期接口为软旋转（实测旧 token 换新后仍可用），悬浮窗和浏览器共用同一条凭证链不会互相踢下线。
- **约 90 天到期**：过期后卡片显示灰字提示（含本地解码的有效期），按上面步骤重新复制一次即可。
- 也支持环境变量 `KIMI_REFRESH_TOKEN`。
- 备用方案 `"kimi_auth"`（手动粘贴 access token 或 authorization 头的值）仍兼容，但 15 分钟就过期，仅调试用。

### 配置示例文件

仓库根目录提供 [`config.example.jsonc`](config.example.jsonc)：包含**全部可配置项**及逐项中文说明（含火山方舟三种账号写法、GLM 双通道、Kimi 月度等）。复制为 `config.jsonc` 后按需修改即可。

## 安全须知

- API Key 以**明文**保存在本地 `config.jsonc`（已 `.gitignore`）。若不希望落盘，改用环境变量注入。
- 日志与错误信息不会输出密钥明文。
- 本应用只做**只读**额度查询，绝无购买 / 续费 / 轮换 Key 等写操作。
- App 永不改写你的 `config.jsonc`（注释安全）；自动生成的只有首次模板与 `state.json`。

## 已知限制

- 控制台启动时可能打印若干 `QWindowsWindow::setGeometry` 告警——这是 Qt/Windows 平台层在卡片内容逐步布局时的几何自适应噪音，**不影响窗口最终显示**（最终尺寸总是完整容纳所有卡片），可忽略。
- OpenCode Go 与智谱 `quota/limit` 接口无官方文档，解析已按 **2026-10-14 实测响应**校准（证据：`.omo/evidence/`）；若官方改版需更新对应 Provider 的解析与 fixture。
- 火山方舟 `ark-` API Key 无法直连控制面（实测 400），多账号请用 arkcli profile（见上文）；IAM AK/SK 直连通道为 SigV4 标准实现。
- Kimi 月度会员明细走 kimi.com 网页端非官方接口（需 `refresh_token`），可能随网页改版失效——失败时自动省略月度窗口；官方 `/usages` 的 `totalQuota` 仅作「月度冻结 / 正常」二元展示。
- 智谱鉴权头格式按实测使用「裸 Key」，保留 401 自动换 `Bearer` 的回退。
- 火山 Coding Plan 的「会话」额度窗口实为 5 小时滚动窗口，悬浮窗统一按「5 小时」展示。

## 手动 QA 清单

- [✅] `python -m app.main` 启动后悬浮窗出现在桌面（默认置顶、半透明、圆角深色卡片），系统托盘出现灰色圆点图标。
- [✅] 按住左键可拖动窗口；拖到角落后退出重启，位置保留。
- [✅] 右键菜单包含：立即刷新 / 不透明度 / 始终置顶 / 开机自启 / 隐藏开关（按当前数据出现的窗口类型）/ 退出（全中文）。
- [✅] 重置段显示倒计时：不足 1 天「xx小时xx分后重置」、跨天「xx天xx小时后重置」、不足 1 分钟「即将重置」。
- [✅] 勾选「开机自启」后注册表 Run 键出现 `SomeMonitor` 项（`regedit` 可查），重启系统后自动启动；取消勾选即移除。
- [✅] 打包后 `dist\SomeMonitor.exe` 双击可运行，`config.jsonc` 生成于 exe 同目录。
- [✅] 右键菜单「退出」能真正结束进程（控制台返回提示符）。
- [✅] 终端里 Ctrl+C 能退出，且退出前已保存位置等状态。
- [✅] 拖动不透明度滑块即时生效；重启后保留。
- [✅] 切换「始终置顶」后重启，置顶状态保留。
- [✅] providers 只列已购套餐的厂商时，仅这些厂商出卡片；`visible: false` 的厂商不出现。
- [✅] 每个额度窗口单行显示五段（类型名/进度条/百分比/用量/重置时间）；调整 `card_width` / `row_layout` 后重启生效。
- [✅] 右键菜单勾选「隐藏本月」后所有卡片的本月行消失、重启仍隐藏；取消勾选恢复。
- [✅] 火山 Coding Plan 的额度窗口显示为「5 小时」（原「会话」）。
- [✅] 自动刷新时窗口内容连续更新，无整窗消失再重现的闪烁。
- [✅] 托盘图标颜色随最紧剩余比例变化（绿/黄/红）；悬停显示摘要；左键点击切换悬浮窗显隐。
- [✅] 本机已登录 arkcli 时，火山方舟卡片能出数。
- [✅] 断网后卡片显示「获取失败 HH:MM，显示旧数据」，恢复网络后下一轮自动更新。
- [✅] 旧版（字典式 providers）配置启动时，悬浮窗显示中文迁移提示且不发起采集。

## 开发

```powershell
python -m pytest            # 全量单测（Qt 用离屏模式，无窗口弹出）
python -m pytest tests/test_provider_kimi.py -q
```

代码结构：`app/model.py`（归一化模型）、`app/config.py`（配置）、`app/providers/`（四家厂商 + 框架）、`app/service.py`（调度与降级）、`app/ui/`（悬浮窗与卡片）。
