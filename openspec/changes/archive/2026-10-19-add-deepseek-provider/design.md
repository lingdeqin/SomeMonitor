# Design

## Context

现有架构：`BaseProvider` 三级凭证解析 → `QuotaSnapshot`（窗口列表 + notes）→ `AccountCard`（窗口行/FreezeRow/灰字提示）。四家厂商均为订阅制额度窗口模型。DeepSeek 是**按量付费**账户：无窗口、无百分比、无重置时间，核心数据是余额与当日消费。项目已有两个可借鉴先例：Kimi 月度额度走非官方接口 + 失败灰字降级；`FreezeRow` 证明卡片可承载非进度条行。

外部接口调研结论（2026-10-19，官方文档 + 多个社区项目交叉验证）：

- **官方余额接口**（唯一官方数据源）：`GET https://api.deepseek.com/user/balance`，`Authorization: Bearer <API Key>`。响应 `{is_available, balance_infos: [{currency, total_balance, granted_balance, topped_up_balance}]}`；**金额均为字符串**；`balance_infos` 为多币种数组（CNY/USD 可并存、不可相加），**数组顺序不保证**。`granted_balance` 即「赠送余额」（未过期赠金），官方直接返回。
- **当日消费：无官方接口**。社区两条路径：
  - **差值记账**：轮询官方余额接口累加下降差值（App 未运行期间漏记、充值间隔的消费丢失、币种切换需重置基准）；
  - **控制台非官方接口**：`GET https://platform.deepseek.com/api/v0/usage/by_api_key/cost?start=<秒>&end=<秒>&tz=<偏移秒>`，`Authorization: Bearer <userToken>`（浏览器 `platform.deepseek.com` localStorage 的 `userToken`，**不是 API Key**，会过期）+ `x-client-platform: web`。响应信封 `{code, msg, data: {biz_code, biz_msg, biz_data}}`，**HTTP 200 也可能携带错误码**：`40002`（缺 token）/`40003`（token 无效）→ 凭证失败；`401` 同义；`403` 为前置 WAF。`biz_data.data[]` 按币种分组：`{currency, series: [{api_key, model, buckets: [{time, cost}]}]}`，`cost` 可能是数字或字符串。`tz` 偏移须为整小时（中国 +28800 满足）。

## Goals / Non-Goals

**Goals:**

- DeepSeek 以第五家厂商接入：官方余额接口采集余额/赠送余额/充值余额 + 多币种选择。
- 当日消费双通道：差值记账（零配置默认，估算）+ userToken 精确通道（可选，失败自动回退）。
- 卡片余额行展示，复用既有降级（stale）与灰字提示机制。
- 记账跨重启、跨天、多账号正确。

**Non-Goals:**

- 不做 DeepSeek 用量的历史曲线/月度统计（只做当日）。
- 不自动获取/续期 userToken（无官方续期机制，靠用户手动复制；Kimi 的 refresh_token 模式不适用）。
- 余额卡片不参与托盘告警配色（余额无「剩余百分比」语义，保持灰/不影响整体颜色）。
- 不把记账机制泛化为多厂商框架（DeepSeek 专用，未来按量付费厂商再抽象）。
- 不展示多币种并存的双份余额（单一展示币种 + 配置覆盖）。

## Decisions

### D1 数据模型：`QuotaSnapshot.balance` 新字段，不复用 `QuotaWindow`

余额塞进 `QuotaWindow`（如虚构 `WindowType.BALANCE`）会把金额硬套进 used/total/percent 语义，进度条与百分比无意义，UI 需大量特判。新增独立数据类：

```python
@dataclass
class BalanceInfo:
    currency: Optional[str] = None        # "CNY" / "USD"
    total: Optional[float] = None         # 总余额
    granted: Optional[float] = None       # 赠送余额（未过期赠金）
    topped_up: Optional[float] = None     # 充值余额
    today_spent: Optional[float] = None   # 当日已用
    today_spent_estimated: bool = False   # True = 差值记账估算
```

`QuotaSnapshot` 增加 `balance: Optional[BalanceInfo] = None`。缺省字段不伪造数值，与既有模型哲学一致。备选「全部塞进 notes 灰字」被否：余额是 DeepSeek 的主数据，灰字可见性不足。

### D2 币种选择：账号 `currency` 配置 > 余额最大项

`balance_infos` 顺序不保证、多币种不可相加。规则：账号配置了 `"currency": "CNY"|"USD"` 则取该项（无该币种则回退默认规则）；否则取 `total_balance` 最大的一项（全为 0 时取第一项）。货币符号映射：CNY→`¥`、USD→`$`。展示币种同时决定精确通道与记账的累计口径。

### D3 差值记账：纯函数 + 独立文件 `deepseek_ledger.json`

- **记账逻辑为纯函数**：输入（上次 entry、本次观测余额、本地日期、展示币种）→ 输出新 entry，便于单测覆盖跨天/充值/币种切换/重启。entry 结构：`{"currency": "CNY", "day": "2026-10-19", "last_seen": 105.0, "spent_today": 5.0}`。
- **记账 key = credential 短哈希**（`sha256(api_key)[:16]`）：同一 API Key 即同一账户身份；换 Key 自然重置记账（合理，换 Key 往往是换账户）；避免同 label 多账号冲突。
- **持久化独立文件**而非 state.json：state.json 由 UI 线程（MainWindow）读写，Provider 在采集线程运行，写同一文件会竞争；独立文件职责单一。路径与 config 同目录（`data_dir`，打包后为 exe 目录，与 state.json 落位规则一致）。每次刷新后原子写（临时文件 + `os.replace`），60 秒一次开销可忽略，崩溃最多丢一个刷新周期。备选「退出时写盘」被否：崩溃丢当日累计。
- **线程安全**：多账号经 `ThreadPoolExecutor` 并发采集，provider 内以 `threading.Lock` 保护记账读写。
- 日期界与 `now` 注入：本地日期用既有 `self._now()`（naive local）格式化为 `YYYY-MM-DD`；测试注入固定时钟。

### D4 精确通道：userToken 调控制台接口，失败回退 + 灰字提示

- 请求：`start` = 本地当日零点 epoch 秒，`end` = `start + 86400`，`tz` = 本地时区偏移秒（`datetime.now().astimezone().utcoffset()`）；头部 `Authorization: Bearer <user_token>`、`Accept: application/json`、`x-client-platform: web`；超时 15s（对齐其他 provider）。
- 解析：HTTP 200 后先看信封 `code`（`40002`/`40003` 视为凭证失败）；`biz_data.data[]` 中取 `currency` == 展示币种的项，`sum(to_number(bucket["cost"]))`。当日无消费返回 0 属正常值。
- 失败处理（对齐 Kimi 月度降级模式）：任何凭证失败/网络失败/解析异常 → 当日已用回退记账估算值 + `snapshot.notes` 灰字「今日精确消费获取失败：userToken 可能已过期，请在浏览器 localStorage 重新复制（步骤见 README）」。余额展示不受影响。
- **记账与精确通道并行**：无论精确通道是否可用，每次余额采集都更新记账 entry（last_seen / spent_today）。精确值仅在展示层覆盖 `today_spent`。这样 token 中途失效时，回退的估算是全程持续记账的结果，而非从失效时刻才起步。
- 非官方接口风险接受理由：失败路径全部兜底到官方接口驱动的估算值，最坏情况退化为纯记账模式。

### D5 UI：`BalanceRow` 单行两段组件

- 新增行组件：**单行**两段，从左至右依次为 `今日已用`、余额段；行尾 stretch 右补；风格对齐既有行的固定名称段模式。金额格式固定两位小数（`¥110.00`，货币惯例不去尾随零）；估算时今日已用段显示 `¥5.23（估算）`。
- **余额段展示规则**（用户指定）：名称统一为 `余额`；金额按赠送拆分——赠送 > 0 时为 `¥105.00 + ¥28.00`（充值余额在前、赠送在后；充值余额缺失时以 total - granted 推导并夹取 ≥0），赠送 0/缺失时仅为总余额 `¥105.00`——缺失字段不伪造数值，无法确认赠送即按无赠送展示。
- **余额行宽度独立配置 `balance_row_layout`**（顶层键）：`name_width`（默认 52，与 `row_layout.name_width` 一致）为两段名称默认宽；按段覆盖键 `spent_name_width` / `balance_name_width` 覆盖各段名称宽，未覆盖回退 `name_width`；数值宽 `value_width`（统一）与 `spent_value_width` / `balance_value_width`（按段，优先于统一）设置后该段数值定宽并右对齐（对齐窗口行 percent/usage 段惯例），未设置自适应。取值优先级 `balance_row_layout` > 内置默认（沿用 `row_layout`/`card_width` 的配置模式，经 `MainWindow._make_card` 传入 `AccountCard`）。
- `AccountCard`：余额行独立于 `_sync_rows` 的窗口行字典，由 `_sync_balance` 管理（置于窗口行之后、特殊标签/信息行之前）；`snapshot.balance` 为 None 或 total 缺失时不渲染。
- 缺失省略：今日已用缺失则该段隐藏（`setVisible(False)`，QHBoxLayout 自动左移补位）；`total` 缺失时整个余额区不渲染（此时走错误/未配置分支）。
- 既有机制自动复用：stale 降级（错误 + 上次成功数据 + 失败时间标注）、notes 灰字、隐藏窗口类型（余额行不是窗口类型，不受其影响）。

### D6 注册与配置接线

- `DeepSeekProvider`：`vendor_id = "deepseek"`，`display_name = "DeepSeek"`，`env_names = ("DEEPSEEK_API_KEY",)`，`credential_keys = ("api_key",)`，`requires_credential = True`，无 `discover_cli`（DeepSeek 无 CLI）。`user_token` 解析：账号字段 > `DEEPSEEK_USER_TOKEN` 环境变量。
- `build_providers(config, env=env, data_dir=...)`：新增可选 `data_dir` 参数传给 DeepSeek Provider 做记账落盘；`main.py` 传 `config_path.parent`；测试不传则记账仅内存（path=None 不落盘），便于单测。
- `DEFAULT_CONFIG` / `CONFIG_TEMPLATE` / `config.example.jsonc` 增补 deepseek 条目（含 user_token 可选说明）；README 增补厂商清单、凭证表、userToken 获取步骤（F12 → Application → Local Storage → `platform.deepseek.com` → `userToken` 键，取 JSON 内层 `value`）、已知限制与 QA 项。

## Risks / Trade-offs

- [控制台接口 `/api/v0/*` 为私有接口，可能随平台改版失效] → 全部失败路径兜底回差值记账；README 已知限制注明；解析按社区多方交叉验证的形状编写，fixture 固化。
- [userToken 是会话令牌，会过期，需用户手动重配] → 灰字提示含重配指引；记账兜底保证过期只损失精度不损失功能；文档明确其为可选增强。
- [差值记账天然失真：App 未运行期间漏记、充值间隔消费丢失、余额入库延迟数分钟] → 展示层明确标注「估算」；README 限制说明；刷新周期默认 60s，失真窗口有限。
- [多币种账户只展示单一币种] → `currency` 配置覆盖 + 默认取余额最大项；文档说明。
- [非整小时时区用户（如 UTC+5:30）精确通道 tz 参数受限] → 中国用户不受影响；按偏移取整小时处理并在代码注释说明。
- [记账文件损坏/手改] → 解析失败视为无记账：以当前余额为基准重新起步（当日估算从 0 重计），不崩溃。

## Migration Plan

- 无破坏性变更：旧配置无 `deepseek` 条目 → 不出现卡片、不采集、不生成记账文件；仅当用户显式添加该厂商（或使用新生成的模板）才激活。
- `deepseek_ledger.json` 首次采集时自动创建；删除该文件等价于重置记账。
- 回滚：从 `providers` 数组删除 deepseek 条目即可；残留的 ledger 文件无害，可手删。

## Open Questions

无。
