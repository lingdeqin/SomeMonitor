# Proposal

## Why

开发者同时订阅了多家 AI coding plan（OpenCode Go、火山方舟、智谱 GLM、Kimi），查看额度需要分别执行各家命令或打开各家控制台，缺少一个常驻、一屏尽览的入口；写码过程中额度耗尽被打断的代价高，需要一个随时可瞟的桌面额度状态。

## What Changes

- 新建一个 Windows 桌面悬浮窗应用（本项目首批产品代码，Python + PySide6）
- 内置四家厂商的额度采集 Provider：OpenCode Go、火山方舟（Coding Plan / Agent Plan，个人版/团队版）、智谱 GLM Coding Plan（国内 bigmodel.cn / 国际 z.ai）、Kimi for Coding
- 统一额度数据模型：各厂商返回归一化为「厂商 / 账号 / 计划 / 额度窗口（5小时/周/月/会话）/ 已用 / 总量 / 百分比 / 重置时间」
- 多方式鉴权：每个 Provider 按「显式配置 > 环境变量 > 本机 CLI 登录态自动发现」逐级解析凭证；火山方舟额外支持 arkcli 子进程与 AK/SK 直连双通道
- 自动刷新（默认 60 秒，可配置）+ 手动刷新；单家失败不影响其他家，保留上次成功数据并标注获取时间
- 悬浮窗交互：无边框、默认置顶、半透明、可拖拽、位置记忆；右键菜单（立即刷新 / 不透明度 / 置顶开关 / 退出）；整窗不透明度 0.3–1.0 可调并持久化
- 每厂商支持配置多个账号，每账号一张卡片
- 界面与文档全部使用中文
- 明确不做：任何付费/写操作（购买、续费、轮换 Key）、Kimi 月度会员明细（需非官方网页接口）、账单金额、macOS/Linux 打包、托盘常驻与开机自启

## Capabilities

### New Capabilities
- `quota-providers`: 多厂商 coding plan 额度采集能力——统一数据模型、多方式凭证解析、厂商间故障隔离、每厂商多账号
- `quota-widget`: Windows 悬浮窗展示与交互能力——置顶/透明度/拖拽/右键菜单/自动刷新与降级展示

### Modified Capabilities

（无——项目当前没有任何既有 spec，本变更全部为新增能力）

## Impact

- 代码：新增 `app/` 应用目录（入口、providers、UI、配置、模型、tests），greenfield，不触碰任何现有系统
- 依赖：PySide6（GUI）、httpx（HTTP 客户端）、pytest（测试）；可选外部依赖：本机已安装并登录的 arkcli（火山方舟子进程通道）
- 凭证：API Key 明文保存在本地 `config.json`（文档说明风险与环境变量替代方案；日志与错误信息不输出密钥）
- 外部接口：调用四家厂商的额度查询端点；其中 OpenCode Go 与智谱 monitor 接口为社区实证端点（无官方文档），存在变更风险，设计中已标注应对措施
