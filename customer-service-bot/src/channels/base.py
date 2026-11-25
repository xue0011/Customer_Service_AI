"""
渠道适配基类
────────────
定义不同消息渠道的适配接口。

每个渠道需要实现：
  - receive(): 接收消息（转为统一 Message 格式）
  - send(): 发送回复（从统一 Response 格式转为渠道格式）
  - start() / stop(): 渠道生命周期管理

支持的渠道：
  - 淘宝/天猫
  - 京东
  - 拼多多
  - 得物
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from ..config.schema import Message, Response


class ChannelAdapter(ABC):
    """渠道适配器基类 —— 所有渠道接入手需实现此接口。"""

    def __init__(self, config: dict) -> None:
        self.config = config
        self._running = False

    @property
    @abstractmethod
    def channel_type(self) -> str:
        """渠道类型标识。"""
        ...

    @abstractmethod
    async def start(self) -> None:
        """启动渠道监听。"""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """停止渠道监听。"""
        ...

    @abstractmethod
    async def receive(self) -> AsyncIterator[Message]:
        """接收消息的异步生成器 —— 将渠道原始消息转为统一 Message 格式。"""
        ...

    @abstractmethod
    async def send(self, response: Response) -> bool:
        """发送回复 —— 将统一 Response 格式转为渠道原始消息格式。"""
        ...

    async def health_check(self) -> bool:
        """健康检查。"""
        return self._running
