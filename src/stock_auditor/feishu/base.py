"""飞书通道统一接口：上层调用 ``send_card`` 与可选的 ``upload_image``。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class FeishuError(RuntimeError):
    """飞书发送失败或通道未配置。"""


class FeishuChannel(ABC):
    name: str

    @property
    @abstractmethod
    def configured(self) -> bool:
        """通道参数是否齐全。"""

    @property
    @abstractmethod
    def status(self) -> str:
        """供 ``sa doctor`` 展示的状态文本。"""

    @abstractmethod
    def send_card(self, card: dict[str, Any]) -> str:
        """发送卡片，返回 message_id；失败抛 ``FeishuError``。"""

    def upload_image(self, path: Path) -> str | None:
        """上传图片并返回 image_key；通道不支持图片时返回 ``None``。"""
        del path
        return None


@dataclass(frozen=True)
class UnconfiguredChannel(FeishuChannel):
    """参数缺失时的占位通道。"""

    reason: str = "飞书未配置"
    name: str = "unconfigured"

    @property
    def configured(self) -> bool:
        return False

    @property
    def status(self) -> str:
        return f"未配置：{self.reason}"

    def send_card(self, card: dict[str, Any]) -> str:
        del card
        raise FeishuError(self.status)
