"""工具注册表测试。"""

import pytest

from src.tools.base import FunctionTool
from src.tools.registry import ToolRegistry


class TestToolRegistry:
    """工具注册表单元测试。"""

    @pytest.fixture
    def registry(self):
        return ToolRegistry()

    @pytest.fixture
    def sample_tool(self):
        async def hello(name: str) -> str:
            return f"Hello, {name}!"

        return FunctionTool(
            name="hello",
            description="Say hello",
            func=hello,
        )

    def test_register(self, registry, sample_tool):
        """测试注册工具。"""
        registry.register(sample_tool)
        assert "hello" in registry
        assert len(registry) == 1

    def test_get_definitions(self, registry, sample_tool):
        """测试获取工具定义。"""
        registry.register(sample_tool)
        defs = registry.get_definitions(["hello"])
        assert len(defs) == 1
        assert defs[0]["function"]["name"] == "hello"

    @pytest.mark.asyncio
    async def test_execute(self, registry, sample_tool):
        """测试执行工具。"""
        registry.register(sample_tool)
        result = await registry.execute("hello", name="World")
        assert result["success"] is True
        assert result["data"] == "Hello, World!"

    def test_unregister(self, registry, sample_tool):
        """测试注销工具。"""
        registry.register(sample_tool)
        registry.unregister("hello")
        assert "hello" not in registry
        assert len(registry) == 0

    def test_empty_definition_for_missing_tool(self, registry):
        """测试请求不存在的工具。"""
        defs = registry.get_definitions(["nonexistent"])
        assert len(defs) == 0


class TestFunctionTool:
    """FunctionTool 单元测试。"""

    @pytest.mark.asyncio
    async def test_sync_function(self):
        """测试包装同步函数。"""
        def add(a: int, b: int) -> int:
            return a + b

        tool = FunctionTool(
            name="add",
            description="Add two numbers",
            func=add,
        )
        result = await tool.safe_execute(a=1, b=2)
        assert result["success"] is True
        assert result["data"] == 3

    @pytest.mark.asyncio
    async def test_async_function(self):
        """测试包装异步函数。"""
        async def multiply(a: int, b: int) -> int:
            return a * b

        tool = FunctionTool(
            name="multiply",
            description="Multiply two numbers",
            func=multiply,
        )
        result = await tool.safe_execute(a=3, b=4)
        assert result["success"] is True
        assert result["data"] == 12

    @pytest.mark.asyncio
    async def test_exception_handling(self):
        """测试异常处理。"""
        async def fail():
            raise ValueError("test error")

        tool = FunctionTool(
            name="fail",
            description="Always fails",
            func=fail,
        )
        result = await tool.safe_execute()
        assert result["success"] is False
        assert "test error" in result["error"]
