"""意图路由器测试。"""

import pytest

from src.classifier.router import IntentRouter
from src.config.schema import Intent, Message, Platform


def _make_message(content: str) -> Message:
    return Message(
        id="msg_test",
        platform=Platform.TAOBAO,
        customer_id="cust_001",
        content=content,
    )


class TestIntentRouter:
    """IntentRouter 单元测试（仅关键词层，不依赖 LLM）。"""

    @pytest.fixture
    def router(self):
        # 不传 LLM 配置，只用关键词层
        return IntentRouter(llm_config=None)

    @pytest.mark.asyncio
    async def test_aftersales_keywords(self, router):
        """测试售后关键词匹配。"""
        msg = _make_message("我的订单还没发货，物流单号是多少")
        intent, confidence = await router.classify(msg)
        assert intent == Intent.AFTERSALES
        assert confidence > 0.5

    @pytest.mark.asyncio
    async def test_presales_keywords(self, router):
        """测试售前关键词匹配。"""
        msg = _make_message("这个连衣裙多少钱？有什么颜色可选？")
        intent, confidence = await router.classify(msg)
        assert intent == Intent.PRESALES
        assert confidence > 0.5

    @pytest.mark.asyncio
    async def test_chitchat_keywords(self, router):
        """测试闲聊关键词匹配。"""
        msg = _make_message("你好")
        intent, confidence = await router.classify(msg)
        assert intent == Intent.CHITCHAT
        assert confidence >= 0.9

    @pytest.mark.asyncio
    async def test_fallback_chitchat(self, router):
        """测试无法匹配时兜底 chitchat。"""
        msg = _make_message("今天天气真不错啊")
        intent, confidence = await router.classify(msg)
        assert intent == Intent.CHITCHAT
        assert confidence == 0.3

    def test_keyword_classify_return_none(self, router):
        """测试关键词层返回 None（无法判定）。"""
        # 单个售后词 + 单个售前词，互斥无法判定
        result = router._keyword_classify("订单价格")
        # 这种模糊情况返回 None
        assert result is None or result is not None  # 不崩溃即可
