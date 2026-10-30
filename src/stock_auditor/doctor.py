"""``sa doctor`` 的环境自检项。

只做轻量探测：不写数据库、不改配置；``--send-test`` 时向飞书发一张测试卡片。
"""

from __future__ import annotations

import os
import ssl
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from stock_auditor import paths
from stock_auditor.commercial import create_commercial_source
from stock_auditor.config import Settings, load_settings
from stock_auditor.feishu import build_test_card, create_feishu_channel

_SSL_CONTEXT = ssl.create_default_context()
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str
    required: bool = True


def _check_python() -> CheckResult:
    version = ".".join(str(part) for part in sys.version_info[:3])
    return CheckResult("Python 版本", sys.version_info >= (3, 12), f"{version}（要求 >= 3.12）")


def _check_config() -> tuple[CheckResult, Settings | None]:
    try:
        settings = load_settings()
    except Exception as exc:  # noqa: BLE001 - 配置错误要原样展示
        return CheckResult("配置加载", False, str(exc)), None
    return CheckResult("配置加载", True, str(paths.config_dir())), settings


def _check_dirs() -> CheckResult:
    try:
        paths.ensure_data_dirs()
        probe = paths.data_dir("state") / ".doctor_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return CheckResult("数据目录可写", False, f"{paths.data_root()}：{exc}")
    return CheckResult("数据目录可写", True, str(paths.data_root()))


def _check_llm_key() -> CheckResult:
    key = os.environ.get("LLM_API_KEY", "").strip()
    return CheckResult(
        "大模型密钥",
        bool(key),
        "LLM_API_KEY 已配置" if key else "缺少 LLM_API_KEY",
    )


def _check_llm_api(settings: Settings) -> CheckResult:
    key = os.environ.get("LLM_API_KEY", "").strip()
    if not key:
        return CheckResult("大模型接口", False, "缺少 LLM_API_KEY，未调用")
    if not settings.llm.base_url or not settings.llm.tier1_model:
        return CheckResult("大模型接口", False, "llm.base_url 或 llm.tier1_model 未配置")
    try:
        from openai import OpenAI

        client = OpenAI(
            base_url=settings.llm.base_url,
            api_key=key,
            timeout=20.0,
            max_retries=0,
        )
        client.chat.completions.create(
            model=settings.llm.tier1_model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
        )
    except Exception as exc:  # noqa: BLE001 - 第三方错误原样展示
        return CheckResult("大模型接口", False, str(exc))
    return CheckResult(
        "大模型接口",
        True,
        f"{settings.llm.base_url} / {settings.llm.tier1_model}",
    )


def _check_json_api(
    name: str,
    url: str,
    *,
    params: dict[str, str],
    headers: dict[str, str] | None = None,
    verify: bool | ssl.SSLContext = True,
    trust_env: bool = True,
    validate: Callable[[dict[str, Any]], bool] | None = None,
) -> CheckResult:
    try:
        response = httpx.get(
            url,
            params=params,
            headers=headers,
            timeout=15,
            verify=verify,
            trust_env=trust_env,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:  # noqa: BLE001 - 网络错误原样展示
        return CheckResult(name, False, str(exc))
    if validate is not None and not validate(payload):
        return CheckResult(name, False, "响应内容不符合预期")
    return CheckResult(name, True, "接口可访问")


def _check_quote_api() -> CheckResult:
    url = "https://finance.sina.com.cn/realstock/company/sz000001/hisdata/klc_kl.js"
    try:
        response = httpx.get(
            url,
            headers={"Referer": "https://finance.sina.com.cn", "User-Agent": _USER_AGENT},
            timeout=15,
        )
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        return CheckResult("行情接口（新浪）", False, str(exc))
    if len(response.content) < 100:
        return CheckResult("行情接口（新浪）", False, "响应内容过短")
    return CheckResult("行情接口（新浪）", True, "接口可访问")


def _check_datacenter_api() -> CheckResult:
    return _check_json_api(
        "数据中心接口（东财）",
        "https://datacenter-web.eastmoney.com/api/data/v1/get",
        params={
            "pageSize": "1",
            "pageNumber": "1",
            "reportName": "RPT_ORG_SURVEY",
            "columns": "ALL",
            "source": "WEB",
            "client": "WEB",
            "filter": '(SECURITY_CODE="002773")',
        },
        validate=lambda payload: payload.get("result") is not None,
    )


def _check_sw_api() -> CheckResult:
    return _check_json_api(
        "申万行业接口",
        "https://www.swsresearch.com/institute-sw/api/index_publish/current/",
        params={"page": "1", "page_size": "1", "indextype": "二级行业"},
        headers={"User-Agent": _USER_AGENT},
        verify=_SSL_CONTEXT,
        trust_env=False,
        validate=lambda payload: bool((payload.get("data") or {}).get("results")),
    )


def _check_commercial(settings: Settings) -> CheckResult:
    source = create_commercial_source(settings)
    ok = source.configured or not settings.commercial.enabled
    return CheckResult("商业数据源（可选）", ok, source.status, required=False)


def _check_feishu(send_test: bool) -> CheckResult:
    try:
        channel = create_feishu_channel()
    except Exception as exc:  # noqa: BLE001 - 配置错误原样展示
        return CheckResult("飞书通道", False, str(exc))
    if not channel.configured:
        return CheckResult("飞书通道", False, channel.status)
    if not send_test:
        return CheckResult("飞书通道", True, f"{channel.name} 已配置（未发送）")
    try:
        message_id = channel.send_card(build_test_card(channel.name))
    except Exception as exc:  # noqa: BLE001 - SDK/网络错误原样展示
        return CheckResult("飞书发送", False, str(exc))
    return CheckResult("飞书发送", True, f"已发送测试卡片 message_id={message_id or '未知'}")


def run_checks(send_test: bool = False) -> list[CheckResult]:
    results = [_check_python()]
    config_result, settings = _check_config()
    results.append(config_result)
    results.append(_check_dirs())
    results.append(_check_quote_api())
    results.append(_check_datacenter_api())
    results.append(_check_sw_api())
    if settings is not None:
        results.append(_check_llm_key())
        results.append(_check_llm_api(settings))
        results.append(_check_commercial(settings))
    results.append(_check_feishu(send_test))
    return results
