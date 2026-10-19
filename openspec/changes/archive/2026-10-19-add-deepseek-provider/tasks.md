# Tasks

## 1. 数据模型

- [x] 1.1 `app/model.py` 新增 `BalanceInfo` 数据类（currency/total/granted/topped_up/today_spent/today_spent_estimated，全部可缺省），`QuotaSnapshot` 增加 `balance: Optional[BalanceInfo] = None` 字段；验证：`tests/test_model.py` 新增用例（缺省字段保持 None、含 balance 的快照构造）通过 `python -m pytest tests/test_model.py -q`

## 2. Provider 骨架与官方余额采集

- [x] 2.1 新建 `app/providers/deepseek.py`：`DeepSeekProvider` 骨架（`vendor_id="deepseek"`、`env_names=("DEEPSEEK_API_KEY",)`、`credential_keys=("api_key",)`、`requires_credential=True`、不覆写 `discover_cli`），并注册进 `app/providers/__init__.py` 的类加载表；验证：`tests/test_providers_build.py` 新增用例（deepseek 可实例化、`visible: false` 跳过、无凭证时返回 UNCONFIGURED 快照且不发起网络请求）通过
- [x] 2.2 实现官方余额采集与解析：`GET https://api.deepseek.com/user/balance`（Bearer Key、超时 15s、httpx getter 可注入），金额字符串经 `to_number` 解析，多币种按「账号 `currency` 配置 > 余额最大项」选择，`granted_balance` 缺失保持缺省；新建 fixture `tests/fixtures/deepseek_balance.json`（多币种 + 字符串金额 + 赠送缺失变体）；验证：`tests/test_provider_deepseek.py` 解析用例（字符串金额、币种默认选择、配置覆盖、赠送缺失、401 报中文错误）通过
- [x] 2.3 Provider 采集主流程：`fetch_account` 组装 `QuotaSnapshot`（balance 填充、无窗口行、账户标题），凭证三级解析中 CLI 层缺席的行为确认；验证：fake getter 注入的 `fetch_account` 集成用例通过

## 3. 差值记账

- [x] 3.1 记账纯函数：输入（上次 entry、本次观测余额、展示币种、本地日期）输出新 entry，规则覆盖：首观测建基准、下降累加、上升（充值）只抬基准不计负、跨天归零、币种切换重置；验证：纯函数单测（注入固定日期）覆盖上述五条规则并通过
- [x] 3.2 记账持久化：`deepseek_ledger.json`（key = `sha256(credential)[:16]`，entry 含 currency/day/last_seen/spent_today），原子写（临时文件 + `os.replace`），损坏/缺失文件视为无记账从当前基准重新起步，多账号并发以 `threading.Lock` 保护；验证：临时目录读写往返、损坏文件、并发两账号的单测通过
- [x] 3.3 接线：`build_providers` 增加可选 `data_dir` 参数（传给 DeepSeek Provider；`None` 时仅内存记账不落盘），`app/main.py` 传 `config_path.parent`；每次余额采集后更新记账与落盘；验证：`data_dir=None` 内存模式与 tmp 目录落盘模式的 provider 级单测、`build_providers` 新签名用例通过

## 4. userToken 精确通道

- [x] 4.1 精确通道请求与解析：`user_token` 凭证解析（账号字段 > `DEEPSEEK_USER_TOKEN` 环境变量）；`GET https://platform.deepseek.com/api/v0/usage/by_api_key/cost`（start=本地当日零点 epoch、end=+86400、tz=本地偏移秒取整小时；头 `Authorization: Bearer <token>`、`Accept: application/json`、`x-client-platform: web`）；信封 `code` 40002/40003 与 HTTP 401 判定凭证失败、403 视为不可用；`biz_data.data[]` 按展示币种过滤后对 buckets 的 `cost`（数字/字符串兼容）求和；新建 fixture `tests/fixtures/deepseek_usage_cost.json`；验证：求和、多币种过滤、当日零消费、信封错误码、数字与字符串 cost 的单测通过
- [x] 4.2 失败回退与并行记账：精确通道任何失败 → `today_spent` 取记账估算值并置 `today_spent_estimated=True`，`snapshot.notes` 追加灰字提示（含 userToken 可能过期与重新获取指引）；精确通道成功时仅覆盖展示值，记账仍每轮更新；验证：fake getter 模拟 token 失效/恢复的多轮采集用例（回退、note、并行记账、精确值无估算标注）通过

## 5. UI 余额行

- [x] 5.1 `app/ui/card.py`：`VENDOR_NAMES` 加 `"deepseek": "DeepSeek"`；新增余额行组件（`余额`/`赠送余额`/`今日已用` 三行，名称段固定宽对齐 `name_width`，金额带货币符号 CNY→¥、USD→$ 且固定两位小数，估算值带「（估算）」后缀）；`AccountCard` 在窗口行之后按固定 key 渲染 `snapshot.balance`，字段缺失省略对应行、无 balance 不渲染；验证：`tests/test_ui_card.py` 新增用例（三行展示与金额格式、估算标注、赠送缺失省略、无 balance 不渲染）通过
- [x] 5.2 确认既有降级机制覆盖余额卡：采集失败走 stale（旧数据 + 失败时间标注）、notes 灰字展示、托盘颜色不受余额卡影响（无窗口即不参与剩余百分比）；验证：stale 快照 + notes 的卡片渲染用例通过

## 6. 配置与文档

- [x] 6.1 `app/config.py`：`DEFAULT_CONFIG` 与 `CONFIG_TEMPLATE` 增补 deepseek 条目（含 `user_token` 可选的中文注释）；验证：`tests/test_config.py` 新增模板断言（模板含 deepseek 条目与 user_token 注释）通过
- [x] 6.2 更新 `config.example.jsonc`（deepseek 全量可配置项与逐项中文说明，含 userToken 获取步骤指引）与 `README.md`（厂商清单、凭证配置表、userToken localStorage 获取步骤、估算模式限制说明、已知限制、手动 QA 项增补）；验证：文档字段与实现一致性人工核对，README 新增 QA 项可按步骤执行

## 7. 集成验证

- [x] 7.1 全量测试：`python -m pytest`（Qt 离屏模式）全部通过，无既有用例回归
- [x] 7.2 端到端手动验证：有真实 DeepSeek 凭证时配置后启动悬浮窗核对余额/赠送余额/今日已用出数与刷新（并把实测响应固化到 `.omo/evidence/`）；无凭证时以离屏模式 + fixture 数据驱动 UI 核对卡片渲染与降级文案；验证：README 新增 QA 项逐条勾验

## 8. 余额行独立布局配置

- [x] 8.1 新增顶层配置 `balance_row_layout`（`name_width`，默认 52 与 `row_layout.name_width` 一致）：`app/config.py` 默认值与模板、`app/ui/window.py` 的 `_make_card` 传入、`app/ui/card.py` 的 `AccountCard` 新参数与 `BalanceRows` 改用独立默认；验证：`tests/test_config.py` 断言默认值与模板条目、`tests/test_ui_card.py` 断言余额行名称段按 `balance_row_layout` 对齐且不影响窗口行宽度
- [x] 8.2 更新 `config.example.jsonc` 与 `README.md` 的 `balance_row_layout` 说明；验证：全量 `python -m pytest` 通过无回归

## 9. 余额信息单行三段展示

- [x] 9.1 `app/ui/card.py`：`BalanceRows` 三行竖排重构为 `BalanceRow` **单行三段**（从左至右：今日已用、余额、赠送余额；每段 `[名称（balance name_width 定宽）][数值]`，缺失段隐藏、其余段左移），`_balance_entries` 顺序同步调整，`AccountCard` 引用更新；验证：`tests/test_ui_card.py` 更新三行断言为单行三段断言并新增段顺序用例通过
- [x] 9.2 README / config.example.jsonc 的余额行描述改为单行三段；验证：全量 `python -m pytest` 通过无回归

## 10. 余额段按段宽度覆盖

- [x] 10.1 `app/ui/card.py` 的 `BalanceRow` 支持按段宽度：`balance_row_layout` 增加按段键 `spent_name_width`/`balance_name_width`/`granted_name_width`（覆盖名称宽，回退 `name_width`）与 `spent_value_width`/`balance_value_width`/`granted_value_width` + 统一 `value_width`（数值定宽右对齐，未设置自适应）；验证：`tests/test_ui_card.py` 新增按段覆盖/回退/数值右对齐用例通过
- [x] 10.2 `config.py` 模板注释、`config.example.jsonc`、README 的 `balance_row_layout` 全键说明；验证：全量 `python -m pytest` 通过无回归

## 11. 余额行两段化与赠送余额合并展示

- [x] 11.1 `app/ui/card.py`：余额行三段改**两段**（今日已用、余额段）；余额段合并规则——赠送 > 0 时名称「余额+赠送余额」、金额「充值 + 赠送」（充值缺失时 total - granted 推导），赠送 0/缺失时名称「余额」、金额 total；`BALANCE_SEGMENTS` 改两段；验证：`tests/test_ui_card.py` 更新为两段断言并新增合并/推导/零赠送用例通过
- [x] 11.2 同步 spec/design 与 `CONFIG_TEMPLATE`、`config.example.jsonc`、README（两段描述、去掉 granted_* 配置键）；验证：全量 `python -m pytest` 通过无回归、`openspec validate --strict` 通过

## 12. 余额段名称统一

- [x] 12.1 `app/ui/card.py`：余额段名称统一为「余额」（原赠送 > 0 时的「余额+赠送余额」改回「余额」），数值形式不变（赠送 > 0 时「充值 + 赠送」、否则总额）；同步 spec/design、更新测试断言与 README/CONFIG_TEMPLATE/config.example.jsonc 描述；验证：全量 `python -m pytest` 通过、`openspec validate --strict` 通过
