from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from stock_auditor.config import Settings, load_settings
from stock_auditor.llm.client import (
    LlmCallError,
    LlmClient,
    LlmNotConfiguredError,
    TokenPricing,
)

PROMPT = "请提取事实"


class _FakeCompletions:
    def __init__(self, *, failures: int = 0, content: str = "结果") -> None:
        self.failures = failures
        self.content = content
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if len(self.calls) <= self.failures:
            raise RuntimeError("接口暂时不可用")
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content=self.content))
            ],
            usage=SimpleNamespace(
                prompt_tokens=1000,
                completion_tokens=500,
                total_tokens=1500,
            ),
        )


class _FakeClient:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.chat = SimpleNamespace(completions=completions)


def _settings() -> Settings:
    return load_settings()


def _client(
    tmp_path: Path,
    *,
    failures: int = 0,
    pricing: TokenPricing | None = None,
) -> tuple[LlmClient, _FakeCompletions]:
    completions = _FakeCompletions(failures=failures)
    client = LlmClient(
        _settings(),
        client=_FakeClient(completions),
        cache_dir=tmp_path / "cache",
        pricing=pricing,
    )
    return client, completions


def test_returns_content_and_usage(tmp_path: Path) -> None:
    client, completions = _client(tmp_path)
    response = client.complete(
        PROMPT,
        model="tier1-test",
        prompt_version="1",
        input_hash="abc",
    )
    assert response.content == "结果"
    assert response.usage.input_tokens == 1000
    assert response.usage.output_tokens == 500
    assert response.usage.total_tokens == 1500
    assert response.usage.cost == 0.0
    assert response.usage.cached is False
    assert len(completions.calls) == 1
    assert completions.calls[0]["temperature"] == 0


def test_retries_after_api_error(tmp_path: Path) -> None:
    client, completions = _client(tmp_path, failures=1)
    response = client.complete(
        PROMPT,
        model="tier1-test",
        prompt_version="1",
        input_hash="abc",
    )
    assert response.content == "结果"
    assert len(completions.calls) == 2


def test_raises_after_retries_exhausted(tmp_path: Path) -> None:
    client, completions = _client(tmp_path, failures=10)
    with pytest.raises(LlmCallError):
        client.complete(
            PROMPT,
            model="tier1-test",
            prompt_version="1",
            input_hash="abc",
        )
    assert len(completions.calls) == _settings().llm.max_retries + 1


def test_cache_hit_skips_api_and_costs_nothing(tmp_path: Path) -> None:
    client, completions = _client(
        tmp_path,
        pricing=TokenPricing(input_per_million=1.0, output_per_million=2.0),
    )
    first = client.complete(
        PROMPT,
        model="tier1-test",
        prompt_version="1",
        input_hash="abc",
    )
    second = client.complete(
        PROMPT,
        model="tier1-test",
        prompt_version="1",
        input_hash="abc",
    )
    assert len(completions.calls) == 1
    assert first.usage.cached is False
    assert second.usage.cached is True
    assert second.usage.cost == 0.0
    assert second.content == first.content


def test_cache_key_includes_prompt_version(tmp_path: Path) -> None:
    client, completions = _client(tmp_path)
    client.complete(
        PROMPT, model="tier1-test", prompt_version="1", input_hash="abc"
    )
    client.complete(
        PROMPT, model="tier1-test", prompt_version="2", input_hash="abc"
    )
    assert len(completions.calls) == 2


def test_cost_uses_pricing(tmp_path: Path) -> None:
    client, _ = _client(
        tmp_path,
        pricing=TokenPricing(input_per_million=1.0, output_per_million=2.0),
    )
    response = client.complete(
        PROMPT, model="tier1-test", prompt_version="1", input_hash="abc"
    )
    assert response.usage.cost == pytest.approx(0.002)


def test_unconfigured_client_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    with pytest.raises(LlmNotConfiguredError):
        LlmClient(_settings(), cache_dir=tmp_path / "cache")


def test_empty_model_name_raises(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    with pytest.raises(LlmNotConfiguredError):
        client.complete(PROMPT, model="", prompt_version="1")
