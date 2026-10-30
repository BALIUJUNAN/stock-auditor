"""按配置创建商业源适配器；任何缺失都降级为「未配置」。"""

from __future__ import annotations

import structlog

from stock_auditor.commercial.base import CommercialSource, UnconfiguredSource
from stock_auditor.commercial.choice import ChoiceSource
from stock_auditor.config import Settings

log = structlog.get_logger(__name__)

_PROVIDERS = {"choice": ChoiceSource.from_env}


def create_commercial_source(settings: Settings) -> CommercialSource:
    if not settings.commercial.enabled:
        return UnconfiguredSource("commercial.enabled 为 false")
    provider = (settings.commercial.provider or "").strip().lower()
    factory = _PROVIDERS.get(provider)
    if factory is None:
        return UnconfiguredSource(f"不支持的 provider {provider!r}")
    source = factory()
    log.info("commercial.source", provider=provider, status=source.status)
    return source
