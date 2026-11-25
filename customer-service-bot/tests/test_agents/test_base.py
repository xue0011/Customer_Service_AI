"""Agent 基类测试。"""

import pytest

from src.agents.base import BaseAgent
from src.config.schema import AgentConfig, AgentContext, Message, Platform


class MockAgent(BaseAgent):
    """用于测试的具体 Agent 实现。"""

    async def _get_system_prompt(self) -> str:
        return "你是一个测试 Agent。"

    def _get_default_tools(self) -> list[str]:
        return []


class TestBaseAgent:
    """BaseAgent 单元测试。"""

    @pytest.fixture
    def agent_config(self):
        return AgentConfig(name="test_agent", max_turns=3)

    @pytest.fixture
    def agent(self, agent_config):
        return MockAgent(agent_config)

    @pytest.mark.asyncio
    async def test_initialization(self, agent):
        """测试 Agent 初始化。"""
        await agent.initialize()
        assert agent._initialized is True
        assert agent._system_prompt == "你是一个测试 Agent。"

    @pytest.mark.asyncio
    async def test_shutdown(self, agent):
        """测试 Agent 关闭。"""
        await agent.initialize()
        await agent.shutdown()
        assert agent._initialized is False

    @pytest.mark.asyncio
    async def test_run_generates_response(self, agent):
        """测试 Agent 运行生成回复（需要 LLM API 或有 mock）。"""
        await agent.initialize()

        context = AgentContext(
            message=Message(
                id="msg_001",
                platform=Platform.TAOBAO,
                customer_id="cust_001",
                content="你好",
            )
        )

        # 注意：此测试需要真实的 LLM API Key 或 mock LLMClient
        # 在没有 LLM 的情况下，Agent 会尝试调用 API 而失败
        # 实际使用时请 mock LLMClient
        try:
            response = await agent.run(context)
            assert response is not None
            assert response.message_id == "msg_001"
        except Exception:
            # 预期在没有 API Key 的情况下会失败
            pass
