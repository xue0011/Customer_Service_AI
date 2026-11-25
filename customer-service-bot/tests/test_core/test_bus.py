"""消息总线测试。"""

import pytest

from src.config.schema import Intent, Message, Platform, Response
from src.core.bus import Envelope, MessageBus


def _make_message(content: str = "你好") -> Message:
    return Message(
        id="msg_test",
        platform=Platform.TAOBAO,
        customer_id="cust_001",
        content=content,
    )


class TestMessageBus:
    """MessageBus 单元测试。"""

    @pytest.mark.asyncio
    async def test_subscribe_and_notify(self):
        """测试订阅与通知。"""
        bus = MessageBus()
        received: list[Envelope] = []

        async def handler(env: Envelope) -> Response | None:
            received.append(env)
            env.intent = Intent.PRESALES
            return None

        bus.subscribe("classify", handler)
        message = _make_message()
        await bus.dispatch(message)

        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_chitchat_fallback(self):
        """测试无意图分类时回退到 chitchat。"""
        bus = MessageBus()
        message = _make_message("你好")
        response = await bus.dispatch(message)

        assert response is not None
        assert response.intent == Intent.CHITCHAT
        assert response.agent == "chitchat"

    @pytest.mark.asyncio
    async def test_unsubscribe(self):
        """测试取消订阅。"""
        bus = MessageBus()

        async def handler(env: Envelope) -> Response | None:
            return None

        bus.subscribe("classify", handler)
        assert "classify" in bus._handlers

        bus.unsubscribe("classify", handler)
        assert len(bus._handlers["classify"]) == 0

    @pytest.mark.asyncio
    async def test_history_recorded(self):
        """测试消息历史被记录。"""
        bus = MessageBus()
        await bus.dispatch(_make_message())
        assert len(bus._history) == 1

    @pytest.mark.asyncio
    async def test_presales_routing(self):
        """测试售前意图路由。"""
        bus = MessageBus()
        presales_called: list[bool] = []

        async def classifier(env: Envelope) -> Response | None:
            env.intent = Intent.PRESALES
            return None

        async def presales_handler(env: Envelope) -> Response | None:
            presales_called.append(True)
            env.response = Response(
                message_id=env.message.id,
                content="售前回复",
                intent=Intent.PRESALES,
                agent="presales",
            )
            return env.response

        bus.subscribe("classify", classifier)
        bus.subscribe("presales", presales_handler)

        response = await bus.dispatch(_make_message())
        assert response is not None
        assert response.agent == "presales"
        assert len(presales_called) == 1
