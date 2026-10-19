"""火山方舟（Coding Plan / Agent Plan）额度 Provider。

双通道（design.md D5）：
  transport = "arkcli"  : 子进程调用本机 arkcli（SSO 登录态，零配置）
  transport = "openapi" : AK/SK + 火山 SigV4 签名直连 OpenAPI
  transport = "auto"    : 配置了 AK/SK 走 openapi，否则走 arkcli（默认）
"""
from __future__ import annotations

import hashlib
import hmac
import json
import shutil
import subprocess
import sys
import urllib.parse
from datetime import datetime as _dt
from datetime import timezone as _tz
from typing import Any, Optional

from app.model import (
    ProviderStatus,
    QuotaSnapshot,
    QuotaWindow,
    WindowType,
    parse_datetime,
    to_number,
)
from app.providers.base import BaseProvider

OPENAPI_HOST = "https://ark.cn-beijing.volcengineapi.com"
OPENAPI_REGION = "cn-beijing"
OPENAPI_SERVICE = "ark"
OPENAPI_VERSION = "2024-01-01"
OPENAPI_ACTIONS = ("GetCodingPlanUsage", "GetAFPUsage")

ARKCLI_ARGS = ["usage", "plan", "--format", "json"]

# windowed 打包形态下，arkcli 子进程（npm .cmd 垫片）缺此标志会每轮刷新闪一个终端窗口
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

_ARK_KEY_ONLY_ERROR = (
    "检测到 ark- API Key 但缺少 secret_access_key：ARK API Key 无法直接查询"
    "控制面额度接口（实测返回 400）。多账号请选择："
    "1) IAM AK/SK 直连（推荐）：各账号在火山控制台创建 IAM 访问密钥，"
    "配置 access_key_id + secret_access_key 成对使用；"
    "2) arkcli profile：各账号分别 arkcli auth login 后按 profile 名引用"
    "（注意：同一账号会自动派生多个不同类型 profile、数据相同；"
    "跨账号登录会切换本机激活身份并可能重建 profile 集）。"
    "或删除 access_key_id 以使用本机 arkcli 登录态。"
)


def _arkcli_command(executable: str, profile: Optional[str] = None) -> list:
    cmd = [executable]
    if profile:
        cmd += ["--profile", profile]
    return cmd + ARKCLI_ARGS

PRODUCT_LABELS = {
    "agent-plan": "Agent Plan",
    "coding-plan": "Coding Plan",
    "agent-plan-team": "Agent Plan 团队版",
    "coding-plan-team": "Coding Plan 团队版",
}
EDITION_LABELS = {"personal": "个人版", "team": "团队版"}
PERIOD_LABEL_MAP = {
    "5h": WindowType.FIVE_H,
    "weekly": WindowType.WEEKLY,
    "monthly": WindowType.MONTHLY,
    # Coding Plan 的「会话」窗口即 5 小时滚动窗口，统一按 5 小时展示
    "session": WindowType.FIVE_H,
}


def _first_present(mapping: dict, keys: tuple) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


class ArkProvider(BaseProvider):
    vendor_id = "ark"
    display_name = "火山方舟"
    env_names = ("ARK_ACCESS_KEY_ID",)
    secret_env_names = ("ARK_SECRET_ACCESS_KEY",)
    credential_keys = ("access_key_id", "api_key")
    requires_credential = False  # arkcli 子进程通道无需应用内凭证

    def resolve_secret(self, account: dict) -> Optional[str]:
        for key in ("secret_access_key", "secret_key"):
            value = account.get(key)
            if value:
                return str(value)
        for name in self.secret_env_names:
            value = self._env.get(name)
            if value:
                return value
        return None

    def transport(self, account: dict) -> str:
        configured = str(
            account.get("transport") or self.provider_config().get("transport") or "auto"
        )
        return configured if configured in ("auto", "arkcli", "openapi") else "auto"

    def select_transport(self, account: dict, access_key: Optional[str], secret: Optional[str]) -> str:
        """auto：AK/SK 齐全走 openapi；只有 ark- API Key 时明确报错（实测无法直连控制面）。"""
        mode = self.transport(account)
        if mode == "auto":
            if access_key and secret:
                return "openapi"
            if access_key and not secret and str(access_key).startswith("ark-"):
                raise RuntimeError(_ARK_KEY_ONLY_ERROR)
            return "arkcli"
        return mode

    def fetch_account(self, account: dict, credential: str) -> list:
        access_key = credential or None
        secret = self.resolve_secret(account)
        label = self.account_label(account)
        # profile 是 arkcli 控制面的多账号机制（--api-key 仅数据面，控制面不消费）
        profile = str(account.get("profile") or "")
        if profile:
            return self._fetch_arkcli(label, profile=profile)
        mode = self.select_transport(account, access_key, secret)
        if mode == "arkcli":
            return self._fetch_arkcli(label)
        return self._fetch_openapi(access_key or "", secret or "", label)

    def fetch_all(self) -> list:
        snapshots = super().fetch_all()
        self._mark_duplicate_viewer_accounts(snapshots)
        return snapshots

    @staticmethod
    def _mark_duplicate_viewer_accounts(snapshots: list) -> None:
        """多个账号解析到同一火山账号 ID 时，给后续卡片加可见标注。

        一次 SSO 登录会为同一账号派生多个不同类型 profile（coding-plan_xxx /
        platform_xxx），用户容易误当多账号配置——直接在 UI 上点破。
        """
        first_label = {}
        for snapshot in snapshots:
            account = snapshot.viewer_account_id
            if not account:
                continue
            if account in first_label:
                if snapshot.account_label != first_label[account]:
                    snapshot.plan_label += "（与其他账号为同一火山账号）"
            else:
                first_label[account] = snapshot.account_label

    # ---------- arkcli 子进程通道 ----------

    def _fetch_arkcli(self, label: str, profile: Optional[str] = None) -> list:
        executable = shutil.which("arkcli")
        if executable is None:
            raise RuntimeError(
                "未找到 arkcli，请先安装：npm i -g @volcengine/ark-cli（或配置 AK/SK 走直连）"
            )
        try:
            proc = subprocess.run(
                _arkcli_command(executable, profile),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=90,
                creationflags=_NO_WINDOW,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("arkcli 调用超时（90 秒）")
        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            stdout = (proc.stdout or "").strip()
            err_text = stderr or stdout
            lowered = err_text.lower()
            if (
                "auth" in lowered
                or "login" in lowered
                or "401" in err_text
                or "accessdenied" in lowered.replace(" ", "")
                or "profile" in lowered
            ):
                raise RuntimeError(
                    "arkcli 未登录 / 凭证失效 / profile 不存在，"
                    "请先运行：arkcli auth login（或核对 profile 名）"
                )
            raise RuntimeError(f"arkcli 调用失败：{err_text[:300]}")
        return parse_arkcli_output(proc.stdout, label)

    # ---------- SigV4 直连通道 ----------

    def _fetch_openapi(self, access_key: str, secret: str, label: str) -> list:
        import httpx

        snapshots = []
        for action in OPENAPI_ACTIONS:
            params = {"Action": action, "Version": OPENAPI_VERSION}
            headers = sigv4_headers(
                "GET",
                OPENAPI_HOST,
                params,
                access_key,
                secret,
                region=OPENAPI_REGION,
                service=OPENAPI_SERVICE,
            )
            resp = httpx.get(OPENAPI_HOST + "/", params=params, headers=headers, timeout=15)
            if resp.status_code != 200:
                raise RuntimeError(
                    f"{action} 请求失败（HTTP {resp.status_code}）：{resp.text[:200]}"
                )
            snapshots.extend(parse_openapi_action(resp.json(), label, action))
        return snapshots


def sigv4_headers(
    method: str,
    url: str,
    params: dict,
    access_key: str,
    secret_key: str,
    region: str = OPENAPI_REGION,
    service: str = OPENAPI_SERVICE,
) -> dict:
    """构造火山引擎 Signature V4 请求头（GET、空 body）。

    密钥链：HMAC(sk, date) -> HMAC(region) -> HMAC(service) -> HMAC("request")；
    算法标签 HMAC-SHA256；签名头 content-type;host;x-content-sha256;x-date。
    """
    now = _dt.now(_tz.utc)
    x_date = now.strftime("%Y%m%dT%H%M%SZ")
    datestamp = now.strftime("%Y%m%d")

    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc
    canonical_uri = parsed.path or "/"
    sorted_params = sorted((str(k), str(v)) for k, v in params.items())
    canonical_query = urllib.parse.urlencode(sorted_params, quote_via=urllib.parse.quote)

    payload_hash = hashlib.sha256(b"").hexdigest()
    canonical_headers = (
        f"content-type:application/json\n"
        f"host:{host}\n"
        f"x-content-sha256:{payload_hash}\n"
        f"x-date:{x_date}\n"
    )
    signed_headers = "content-type;host;x-content-sha256;x-date"
    canonical_request = "\n".join(
        [
            method.upper(),
            canonical_uri,
            canonical_query,
            canonical_headers,
            signed_headers,
            payload_hash,
        ]
    )
    credential_scope = f"{datestamp}/{region}/{service}/request"
    string_to_sign = "\n".join(
        [
            "HMAC-SHA256",
            x_date,
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )

    def _hmac(key: bytes, message: str) -> bytes:
        return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()

    key_date = _hmac(secret_key.encode("utf-8"), datestamp)
    key_region = _hmac(key_date, region)
    key_service = _hmac(key_region, service)
    key_signing = _hmac(key_service, "request")
    signature = hmac.new(
        key_signing, string_to_sign.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    authorization = (
        f"HMAC-SHA256 Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return {
        "Content-Type": "application/json",
        "X-Date": x_date,
        "x-content-sha256": payload_hash,
        "Authorization": authorization,
    }


def parse_arkcli_output(text: str, label: str = "默认") -> list:
    """解析 `arkcli usage plan --format json` 输出（schema 见 arkcli 官方文档）。"""
    data = json.loads(text)
    if not isinstance(data, dict):
        raise RuntimeError("arkcli 输出不是 JSON 对象")
    viewer = data.get("viewer") if isinstance(data.get("viewer"), dict) else {}
    viewer_account = str(viewer.get("account_id")) if viewer.get("account_id") else None
    snapshots = []
    for item in data.get("items") or []:
        if not isinstance(item, dict):
            continue
        product = str(item.get("product") or "ark")
        plan_label = PRODUCT_LABELS.get(product, product)
        edition = str(item.get("edition") or "")
        if edition in EDITION_LABELS:
            plan_label += f" · {EDITION_LABELS[edition]}"
        tier = item.get("tier")
        if tier:
            plan_label += f" · {tier}"
        snapshot = QuotaSnapshot(
            vendor="ark",
            account_label=label,
            plan_label=plan_label,
            viewer_account_id=viewer_account,
        )
        error = item.get("error")
        if error:
            snapshot.status = ProviderStatus.ERROR
            snapshot.error = str(error)
            snapshots.append(snapshot)
            continue
        if not item.get("subscribed"):
            # 未订阅：展示「未订阅」而非 0%
            snapshots.append(snapshot)
            continue
        for period in item.get("periods") or []:
            if not isinstance(period, dict):
                continue
            window_type = PERIOD_LABEL_MAP.get(str(period.get("label") or "").lower())
            if window_type is None:
                continue
            used = to_number(period.get("used"))
            total = to_number(period.get("total"))
            percent = to_number(period.get("percent"))
            # CodingPlan 后端实测按 0-1 比率下发 percent（证据：.omo/evidence/ark_live.json），
            # 而 AgentPlan 的 percent 由 arkcli 以 used/total*100 计算（0-100）；
            # 仅在缺 used/total（CodingPlan 形态）且值 <= 1 时按比率归一化为百分比
            if percent is not None and used is None and total is None and percent <= 1.0:
                percent = round(percent * 100.0, 2)
            window = QuotaWindow(
                type=window_type,
                used=used,
                total=total,
                percent=percent,
                reset_at=parse_datetime(period.get("reset_at")),
            )
            window.ensure_derived()
            snapshot.windows.append(window)
        snapshots.append(snapshot)
    return snapshots


def parse_openapi_action(body: Any, label: str, action: str) -> list:
    """防御式解析直连 OpenAPI 响应。

    arkcli 已在后端做过归一化；直连拿到的是原始响应，字段形状文档不全，
    这里按「寻找 periods/QuotaUsage 风格窗口」尽力解析，无法识别时给出明确错误。
    """
    plan_label = "Coding Plan" if "Coding" in action else "Agent Plan"
    snapshot = QuotaSnapshot(vendor="ark", account_label=label, plan_label=plan_label)
    found = []

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            percent = to_number(_first_present(node, ("percent", "Percent")))
            label_raw = str(
                _first_present(node, ("label", "Label", "type", "Type", "windowType")) or ""
            ).lower()
            window_type = PERIOD_LABEL_MAP.get(label_raw)
            if percent is not None and window_type is not None:
                window = QuotaWindow(
                    type=window_type,
                    percent=percent,
                    used=to_number(_first_present(node, ("used", "Used"))),
                    total=to_number(_first_present(node, ("total", "Total"))),
                    reset_at=parse_datetime(
                        _first_present(node, ("reset_at", "resetAt", "resetTime", "ResetTime"))
                    ),
                )
                window.ensure_derived()
                found.append(window)
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for value in node:
                _walk(value)

    _walk(body)
    if not found:
        raise RuntimeError(
            f"{action} 响应无法解析（未识别到额度窗口字段）；建议改用 transport=arkcli"
        )
    snapshot.windows = found
    return [snapshot]
