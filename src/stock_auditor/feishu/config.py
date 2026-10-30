"""读取 ``config/local/feishu.yaml``；密钥只从 ``.env`` 读取。"""

from __future__ import annotations

from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from stock_auditor import paths

CONFIG_FILENAME = "feishu.yaml"


class FeishuConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    channel: Literal["app", "webhook"]
    chat_id: str = ""
    allowed_chat_ids: list[str] = Field(default_factory=list)
    allowed_user_ids: list[str] = Field(default_factory=list)


def load_feishu_config() -> FeishuConfig | None:
    path = paths.local_config_dir() / CONFIG_FILENAME
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"飞书配置顶层必须是映射：{path}")
    return FeishuConfig.model_validate(data)
