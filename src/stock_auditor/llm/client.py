"""OpenAI 兼容模型客户端：重试、缓存、用量与费用记录。

缓存键为「模型名 + 提示词版本 + 输入材料哈希」。命中缓存时不调用接口，
``LlmUsage.cached`` 为 True、费用记 0。
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog
from openai import OpenAI

from stock_auditor import paths
from stock_auditor.config import Settings

log = structlog.get_logger(__name__)

_CACHE_SUBDIR = "llm"


class LlmNotConfiguredError(RuntimeError):
    """缺少 API Key 或 base_url。"""


class LlmCallError(RuntimeError):
    """重试耗尽后仍调用失败。"""


@dataclass(frozen=True)
class TokenPricing:
    """每百万 token 的单价（人民币元）。"""

    input_per_million: float
    output_per_million: float

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens * self.input_per_million
            + output_tokens * self.output_per_million
        ) / 1_000_000


@dataclass(frozen=True)
class LlmUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0
    duration_seconds: float = 0.0
    cached: bool = False


@dataclass(frozen=True)
class LlmResponse:
    content: str
    model: str
    prompt_version: str
    usage: LlmUsage


def _cache_path(
    cache_dir: Path, model: str, prompt_version: str, input_hash: str
) -> Path:
    digest = hashlib.sha256(
        f"{model}\0{prompt_version}\0{input_hash}".encode()
    ).hexdigest()
    return cache_dir / f"{digest}.json"


def _resolve_base_url(settings: Settings) -> str:
    return os.environ.get("LLM_BASE_URL", "").strip() or settings.llm.base_url.strip()


def _resolve_api_key() -> str:
    return os.environ.get("LLM_API_KEY", "").strip()


class LlmClient:
    def __init__(
        self,
        settings: Settings,
        *,
        client: Any | None = None,
        cache_dir: Path | None = None,
        pricing: TokenPricing | None = None,
    ) -> None:
        self._settings = settings
        self._pricing = pricing
        self._cache_dir = (
            Path(cache_dir)
            if cache_dir is not None
            else paths.cache_dir() / _CACHE_SUBDIR
        )
        if client is not None:
            self._client: Any = client
        else:
            base_url = _resolve_base_url(settings)
            api_key = _resolve_api_key()
            if not base_url or not api_key:
                raise LlmNotConfiguredError(
                    "模型未配置：请设置 LLM_BASE_URL 与 LLM_API_KEY"
                )
            self._client = OpenAI(
                base_url=base_url,
                api_key=api_key,
                max_retries=0,
            )

    def complete(
        self,
        prompt: str,
        *,
        model: str,
        prompt_version: str,
        input_hash: str | None = None,
        response_format: Mapping[str, Any] | None = None,
        messages: Sequence[Mapping[str, str]] | None = None,
    ) -> LlmResponse:
        if not model.strip():
            raise LlmNotConfiguredError("模型名称为空：请配置 llm.tier1_model / tier2_model")
        digest = input_hash or hashlib.sha256(prompt.encode()).hexdigest()
        cache_file = _cache_path(
            self._cache_dir, model, prompt_version, digest
        )
        cached = self._read_cache(cache_file)
        if cached is not None:
            log.info(
                "llm.cache_hit",
                model=model,
                prompt_version=prompt_version,
                input_hash=digest,
            )
            return LlmResponse(
                content=cached["content"],
                model=model,
                prompt_version=prompt_version,
                usage=LlmUsage(
                    input_tokens=cached.get("input_tokens", 0),
                    output_tokens=cached.get("output_tokens", 0),
                    total_tokens=cached.get("total_tokens", 0),
                    cost=0.0,
                    cached=True,
                ),
            )

        payload: list[dict[str, str]] = (
            [dict(item) for item in messages]
            if messages is not None
            else [{"role": "user", "content": prompt}]
        )
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": payload,
            "temperature": self._settings.llm.temperature,
        }
        if response_format is not None:
            kwargs["response_format"] = dict(response_format)

        attempts = self._settings.llm.max_retries + 1
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            started = time.perf_counter()
            try:
                completion = self._client.chat.completions.create(**kwargs)
                content = completion.choices[0].message.content
                if content is None:
                    raise ValueError("模型返回内容为空")
                usage = getattr(completion, "usage", None)
                input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
                output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
                total_tokens = int(
                    getattr(usage, "total_tokens", 0)
                    or input_tokens + output_tokens
                )
                cost = (
                    self._pricing.cost(input_tokens, output_tokens)
                    if self._pricing is not None
                    else 0.0
                )
                duration = time.perf_counter() - started
                self._write_cache(
                    cache_file,
                    {
                        "content": content,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "total_tokens": total_tokens,
                    },
                )
                log.info(
                    "llm.call",
                    model=model,
                    prompt_version=prompt_version,
                    input_hash=digest,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    cost=cost,
                    duration_seconds=round(duration, 3),
                    attempt=attempt,
                )
                return LlmResponse(
                    content=content,
                    model=model,
                    prompt_version=prompt_version,
                    usage=LlmUsage(
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        total_tokens=total_tokens,
                        cost=cost,
                        duration_seconds=duration,
                    ),
                )
            except Exception as exc:
                last_error = exc
                log.warning(
                    "llm.call_failed",
                    model=model,
                    prompt_version=prompt_version,
                    attempt=attempt,
                    error=str(exc),
                )
        raise LlmCallError(f"模型调用失败（重试 {attempts - 1} 次）：{last_error}")

    @staticmethod
    def _read_cache(path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict) or not isinstance(data.get("content"), str):
            return None
        return data

    @staticmethod
    def _write_cache(path: Path, payload: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(path)
