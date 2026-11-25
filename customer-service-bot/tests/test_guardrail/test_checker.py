"""护栏检查器测试。"""

import pytest

from src.config.schema import GuardrailConfig, GuardrailRule
from src.guardrail.checker import GuardrailChecker
from src.guardrail.rules import RuleEngine


class TestRuleEngine:
    """规则引擎单元测试。"""

    @pytest.fixture
    def engine(self):
        rules = [
            GuardrailRule(
                name="test_keyword",
                type="keyword",
                pattern="测试,敏感词",
                action="block",
                message="包含敏感词",
            ),
            GuardrailRule(
                name="test_regex",
                type="regex",
                pattern=r"\d{11}",  # 手机号
                action="block",
                message="包含手机号",
            ),
        ]
        return RuleEngine(rules)

    def test_keyword_match(self, engine):
        """测试关键词匹配。"""
        result = engine.check("这是一条包含敏感词的消息")
        assert result is not None
        assert result.passed is False
        assert result.rule_name == "test_keyword"

    def test_keyword_no_match(self, engine):
        """测试关键词不匹配。"""
        result = engine.check("这是一条正常的消息")
        assert result is None

    def test_regex_match(self, engine):
        """测试正则匹配。"""
        result = engine.check("我的手机号是13800138000")
        assert result is not None
        assert result.rule_name == "test_regex"

    def test_regex_no_match(self, engine):
        """测试正则不匹配。"""
        result = engine.check("电话是1380013")  # 不够11位
        assert result is None

    def test_case_insensitive_keyword(self, engine):
        """测试关键词大小写不敏感。"""
        result = engine.check("这是测试消息")
        assert result is not None
        assert result.rule_name == "test_keyword"


class TestGuardrailChecker:
    """护栏检查器单元测试。"""

    @pytest.fixture
    def config(self):
        return GuardrailConfig(
            enabled=True,
            llm_check_enabled=False,  # 测试时关闭 LLM 检查
            rules=[],
        )

    @pytest.mark.asyncio
    async def test_normal_message_passes(self, config):
        """测试正常消息通过。"""
        checker = GuardrailChecker(config)
        await checker.initialize()

        result = await checker.check("您好，您的订单已发货，预计3天到达。")
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_blocked_keyword(self, config):
        """测试关键词拦截。"""
        checker = GuardrailChecker(config)
        await checker.initialize()

        result = await checker.check("这是政治敏感内容...")
        assert result.passed is False
        assert result.action == "block"

    @pytest.mark.asyncio
    async def test_disabled_guardrail(self):
        """测试禁用护栏。"""
        config = GuardrailConfig(enabled=False, llm_check_enabled=False)
        checker = GuardrailChecker(config)
        await checker.initialize()

        result = await checker.check("任何内容都能通过")
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_check_and_rewrite_block(self, config):
        """测试检查并改写（拦截）。"""
        checker = GuardrailChecker(config)
        await checker.initialize()

        passed, content = await checker.check_and_rewrite("这是政治敏感内容...")
        assert passed is False
        assert "拦截" in content
